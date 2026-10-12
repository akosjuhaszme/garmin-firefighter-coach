"""
Modular MCP Server for Garmin Connect Data
"""

import contextlib
import json
import os
import socket
import sys
import threading

import requests
import urllib3.util.connection as _urllib3_connection
from mcp.server.fastmcp import FastMCP

from garth.exc import GarthHTTPError
from garminconnect import Garmin, GarminConnectAuthenticationError

# Import required modules
from garmin_workouts_mcp import activity_management
from garmin_workouts_mcp import workouts
from garmin_workouts_mcp import workout_templates
from garmin_workouts_mcp import recovery
from garmin_workouts_mcp import weather
from garmin_workouts_mcp import routes
from garmin_workouts_mcp import tracking
from garmin_workouts_mcp import prompts

# Prefer IPv4 for every outbound HTTP call this server makes (Garmin, OpenRouteService,
# OpenWeatherMap - all reachable over IPv4). Found live: on a machine whose IPv6 route
# to Cloudflare is black-holed, connectapi.garmin.com resolves to 5 AAAA + 5 A records;
# urllib3 tries the AAAA addresses first, each one hangs until the OS connect timeout,
# and only then falls back to IPv4 - ~50s before the first byte, versus 0.4s with IPv4
# only. That made the startup login outlast the MCP client's 30s CONNECT_TIMEOUT, so
# the server never connected at all. Set GARMIN_MCP_ALLOW_IPV6=1 to keep dual-stack
# behaviour (e.g. on an IPv6-only network).
if os.environ.get("GARMIN_MCP_ALLOW_IPV6", "").lower() not in ("1", "true", "yes"):
    _urllib3_connection.allowed_gai_family = lambda: socket.AF_INET

# How long a tool call waits for the background login (see _LazyGarminClient) to finish.
_LOGIN_WAIT_SECONDS = 120


class _LazyGarminClient:
    """Stand-in for the Garmin client that lets the MCP server answer `initialize`
    immediately while the login runs in a background thread.

    Doing the login before app.run() meant any slow network (token refresh, DNS,
    broken IPv6, Garmin throttling) made the whole server miss the MCP client's
    30s connect timeout and show up as "failed to connect" with no explanation.
    Now the handshake never waits on Garmin; tool calls block until the login
    finishes (or fail with the real login error message instead of a timeout).
    """

    def __init__(self):
        self._ready = threading.Event()
        self._client = None
        self._error = None

    def _finish(self, client, error=None):
        self._client = client
        self._error = error
        self._ready.set()

    def __getattr__(self, name):
        # Only reached for attributes not found on the proxy itself.
        if not self._ready.wait(timeout=_LOGIN_WAIT_SECONDS):
            raise RuntimeError(
                f"Garmin login is still in progress after {_LOGIN_WAIT_SECONDS}s - "
                "check network connectivity to connectapi.garmin.com and retry."
            )
        if self._client is None:
            raise RuntimeError(
                self._error
                or "Garmin login failed - run 'garmin-mcp-auth' to re-authenticate."
            )
        attr = getattr(self._client, name)
        if callable(attr) and name.startswith(_RETRY_READ_PREFIXES):
            return _retry_once_on_dropped_connection(attr)
        return attr


# Read-only client methods get one retry when Garmin drops the connection
# (RemoteDisconnected right after a restart or on an idle pooled connection).
# Writes are never retried automatically: a retried upload or schedule could
# create a duplicate if the first attempt actually went through.
_RETRY_READ_PREFIXES = ("get_", "count_", "download_")
_DROPPED_CONNECTION_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.ChunkedEncodingError,
)


def _retry_once_on_dropped_connection(method):
    def call(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except _DROPPED_CONNECTION_ERRORS:
            return method(*args, **kwargs)

    call.__name__ = getattr(method, "__name__", "call")
    call.__doc__ = getattr(method, "__doc__", None)
    return call


def _persist_refreshed_tokens(garmin, tokenstore_path):
    """garth refreshes an expired OAuth2 token in memory during login but never
    writes it back, so every later start repeats the refresh (an extra
    round-trip to Garmin each time). Save it when it differs from what's on disk."""
    with contextlib.suppress(Exception):
        path = os.path.join(os.path.expanduser(tokenstore_path), "oauth2_token.json")
        with open(path, "r", encoding="utf-8") as f:
            on_disk = json.load(f)
        if on_disk.get("expires_at") != garmin.garth.oauth2_token.expires_at:
            garmin.garth.dump(os.path.expanduser(tokenstore_path))


def is_interactive_terminal() -> bool:
    """Detect if running in interactive terminal vs MCP subprocess.

    Returns:
        bool: True if running in an interactive terminal, False otherwise
    """
    return sys.stdin.isatty() and sys.stdout.isatty()


def get_mfa() -> str:
    """Get MFA code from user input.

    Raises:
        RuntimeError: If running in non-interactive environment
    """
    if not is_interactive_terminal():
        print(
            "\nERROR: MFA code required but no interactive terminal available.\n"
            "Please run 'garmin-mcp-auth' in your terminal first.\n"
            "See: https://github.com/brunosantos/garmin-workouts-mcp?tab=readme-ov-file#step-1-pre-authenticate-one-time\n",
            file=sys.stderr,
        )
        raise RuntimeError("MFA required but non-interactive environment")

    print(
        "\nGarmin Connect MFA required. Please check your email/phone for the code.",
        file=sys.stderr,
    )
    return input("Enter MFA code: ")


# Get credentials from environment
email = os.environ.get("GARMIN_EMAIL")
email_file = os.environ.get("GARMIN_EMAIL_FILE")
if email and email_file:
    raise ValueError(
        "Must only provide one of GARMIN_EMAIL and GARMIN_EMAIL_FILE, got both"
    )
elif email_file:
    with open(email_file, "r") as email_file:
        email = email_file.read().rstrip()

password = os.environ.get("GARMIN_PASSWORD")
password_file = os.environ.get("GARMIN_PASSWORD_FILE")
if password and password_file:
    raise ValueError(
        "Must only provide one of GARMIN_PASSWORD and GARMIN_PASSWORD_FILE, got both"
    )
elif password_file:
    with open(password_file, "r") as password_file:
        password = password_file.read().rstrip()

tokenstore = os.getenv("GARMINTOKENS") or "~/.garminconnect"
tokenstore_base64 = os.getenv("GARMINTOKENS_BASE64") or "~/.garminconnect_base64"
is_cn = os.getenv("GARMIN_IS_CN", "false").lower() in ("true", "1", "yes")


def init_api(email, password):
    """Initialize Garmin API with your credentials."""
    import io

    try:
        # Using Oauth1 and OAuth2 token files from directory
        print(
            f"Trying to login to Garmin Connect using token data from directory '{tokenstore}'...\n",
            file=sys.stderr,
        )

        # Suppress stderr for token validation to avoid confusing library errors
        old_stderr = sys.stderr
        sys.stderr = io.StringIO()

        try:
            garmin = Garmin(is_cn=is_cn)
            garmin.login(tokenstore)
            _persist_refreshed_tokens(garmin, tokenstore)
        finally:
            sys.stderr = old_stderr

    except (FileNotFoundError, GarthHTTPError, GarminConnectAuthenticationError):
        # Session has expired. You'll need to log in again

        # Check if we're in a non-interactive environment without credentials
        if not is_interactive_terminal() and (not email or not password):
            print(
                "ERROR: OAuth tokens not found and no interactive terminal available.\n"
                "Please authenticate first:\n"
                "  1. Run: garmin-mcp-auth\n"
                "  2. Enter your credentials and MFA code\n"
                "  3. Restart your MCP client\n"
                f"Tokens will be saved to: {tokenstore}\n",
                file=sys.stderr,
            )
            return None

        print(
            "Login tokens not present, login with your Garmin Connect credentials to generate them.\n"
            f"They will be stored in '{tokenstore}' for future use.\n",
            file=sys.stderr,
        )
        try:
            garmin = Garmin(
                email=email, password=password, is_cn=is_cn, prompt_mfa=get_mfa
            )
            garmin.login()
            # Save Oauth1 and Oauth2 token files to directory for next login
            garmin.garth.dump(tokenstore)
            print(
                f"Oauth tokens stored in '{tokenstore}' directory for future use. (first method)\n",
                file=sys.stderr,
            )
            # Encode Oauth1 and Oauth2 tokens to base64 string and safe to file for next login (alternative way)
            token_base64 = garmin.garth.dumps()
            dir_path = os.path.expanduser(tokenstore_base64)
            with open(dir_path, "w") as token_file:
                token_file.write(token_base64)
            print(
                f"Oauth tokens encoded as base64 string and saved to '{dir_path}' file for future use. (second method)\n",
                file=sys.stderr,
            )
        except (
            FileNotFoundError,
            GarthHTTPError,
            GarminConnectAuthenticationError,
            requests.exceptions.HTTPError,
        ) as err:
            error_msg = str(err)

            # Provide clean, actionable error messages
            print("\nAuthentication failed.", file=sys.stderr)

            if isinstance(err, GarminConnectAuthenticationError):
                if "MFA" in error_msg or "code" in error_msg.lower():
                    print("MFA code may be incorrect or expired.", file=sys.stderr)
                else:
                    print("Invalid email or password.", file=sys.stderr)
            elif isinstance(err, GarthHTTPError):
                if "401" in error_msg or "Unauthorized" in error_msg:
                    print(
                        "Invalid credentials. Please check your email and password.",
                        file=sys.stderr,
                    )
                elif "429" in error_msg:
                    print(
                        "Too many requests. Please wait and try again.", file=sys.stderr
                    )
                elif "500" in error_msg or "503" in error_msg:
                    print(
                        "Garmin Connect service issue. Please try again later.",
                        file=sys.stderr,
                    )
                else:
                    print(f"Error: {error_msg.split(':')[0]}", file=sys.stderr)
            elif isinstance(err, requests.exceptions.HTTPError):
                print("Network error. Please check your connection.", file=sys.stderr)
            else:
                print(f"Error: {error_msg.split(':')[0]}", file=sys.stderr)

            print(
                f"\nTip: Run 'garmin-mcp-auth' to authenticate interactively.",
                file=sys.stderr,
            )
            return None

    return garmin


def main():
    """Initialize the MCP server and register all tools"""

    # Log in on a background thread so the MCP handshake (initialize/list_tools) is
    # answered immediately instead of waiting on Garmin - tool calls wait for it.
    garmin_client = _LazyGarminClient()

    def _login_worker():
        try:
            client = init_api(email, password)
            if client:
                print("Garmin Connect client initialized successfully.", file=sys.stderr)
                garmin_client._finish(client)
            else:
                print("Failed to initialize Garmin Connect client.", file=sys.stderr)
                garmin_client._finish(
                    None,
                    "Garmin login failed (no valid tokens in "
                    f"'{tokenstore}') - run 'garmin-mcp-auth' in a terminal, then restart.",
                )
        except Exception as e:
            garmin_client._finish(None, f"Garmin login failed: {e}")

    threading.Thread(target=_login_worker, name="garmin-login", daemon=True).start()

    # Configure required modules with the Garmin client
    activity_management.configure(garmin_client)
    workouts.configure(garmin_client)
    recovery.configure(garmin_client)
    routes.configure(garmin_client)
    tracking.configure(garmin_client)

    # Create the MCP app
    app = FastMCP(
        "Garmin Connect v1.0",
        instructions=(
            "Garmin Connect training, recovery and body data. If a companion "
            "'mfp-readonly' server (tools named fitness_*) is also connected, it holds "
            "the user's MyFitnessPal food diary: use it for meals and macros. Garmin's "
            "own consumed_kcal (get_daily_summary) is only the calorie total of that "
            "same diary, and workouts recorded here reach MyFitnessPal's exercise "
            "diary. Combine both for questions about training, food and weight."
        ),
    )

    # Register tools from required modules
    app = activity_management.register_tools(app)
    app = workouts.register_tools(app)
    app = recovery.register_tools(app)
    app = weather.register_tools(app)
    app = routes.register_tools(app)
    app = tracking.register_tools(app)

    # Register the ready-made coaching prompts (first-run setup, weekly review, ...)
    app = prompts.register_prompts(app)

    # Register resources (workout templates)
    app = workout_templates.register_resources(app)

    # Run the MCP server
    app.run()


if __name__ == "__main__":
    main()
