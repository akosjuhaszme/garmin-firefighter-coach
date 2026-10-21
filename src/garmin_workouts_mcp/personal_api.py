"""
Garmin Connect Personal API client (official, read-only, pull)

Garmin's Personal API gives one person read access to their own Connect data. The user
creates a key on the Garmin Connect website (Settings, Personal API key; the key is shown
once and expires after 30 days to a year). The key is exchanged for an OAuth2 access token
(valid 24 hours, no refresh token: ask again with the key), and the token is sent as a
bearer token to https://personal.connectapi.garmin.com, whose paths are the same services
this server already reads through the unofficial route (activity-service, sleep-service,
hrv-service, usersummary-service, weight-service, ...). Only GET endpoints exist, so
nothing can be changed through it. It is meant for personal use, not for serving other
people.

This module only talks to that API; nothing else in the server uses it yet. The key is
read from the environment variable GARMIN_PERSONAL_API_KEY, or from a file (default
~/.garmin-coach/personal_api_key.txt, or the path in GARMIN_PERSONAL_API_KEY_FILE).
Neither the key nor the token is ever returned in a message or a log line.
"""
import json
import os
import pathlib
import time
from typing import Optional

import requests

BASE_URL = "https://personal.connectapi.garmin.com"
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
DEFAULT_KEY_FILE = pathlib.Path.home() / ".garmin-coach" / "personal_api_key.txt"
_DEFAULT_LIFETIME = 23 * 3600  # tokens live 24 hours; renew a little early
_TOKEN_NAMES = ("access_token", "accessToken", "token", "jwt", "id_token")


class PersonalApiError(Exception):
    """A problem talking to the Personal API (the message never contains the key or a token)."""


def load_key() -> Optional[str]:
    """The Personal API key from GARMIN_PERSONAL_API_KEY or the key file, or None."""
    key = os.environ.get("GARMIN_PERSONAL_API_KEY", "").strip()
    if key:
        return key
    path = pathlib.Path(os.environ.get("GARMIN_PERSONAL_API_KEY_FILE") or DEFAULT_KEY_FILE)
    try:
        text = path.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return None
    return text or None


def find_values(obj, name: str, limit: int = 1) -> list:
    """The first `limit` values stored under key `name` anywhere in nested JSON (handy for comparing
    two differently shaped answers)."""
    found = []

    def walk(node):
        if len(found) >= limit:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if key == name and not isinstance(value, (dict, list)):
                    found.append(value)
                    if len(found) >= limit:
                        return
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(obj)
    return found


class PersonalApiClient:
    def __init__(self, key: Optional[str] = None, session=None, clock=time.time):
        self._key = key if key is not None else load_key()
        self._session = session or requests.Session()
        self._clock = clock
        self._token = None
        self._expires_at = 0.0
        self.token_shape = None  # names of the fields of the token answer, for diagnostics

    @property
    def configured(self) -> bool:
        return bool(self._key)

    def _scrub(self, text) -> str:
        text = str(text or "")
        for secret in (self._key, self._token):
            if secret:
                text = text.replace(secret, "***")
        return text[:300]

    def _fetch_token(self) -> str:
        if not self._key:
            raise PersonalApiError(
                "No Personal API key found: set GARMIN_PERSONAL_API_KEY or put the key in "
                f"{DEFAULT_KEY_FILE} (or the file named in GARMIN_PERSONAL_API_KEY_FILE)."
            )
        response = self._session.post(
            BASE_URL + TOKEN_PATH, headers={"Authorization": f"ApiKey {self._key}"}, timeout=30
        )
        if response.status_code != 200:
            raise PersonalApiError(
                f"Token request failed: HTTP {response.status_code} {self._scrub(response.text)}"
            )
        try:
            body = response.json()
        except ValueError:
            body = None
        token, lifetime = None, _DEFAULT_LIFETIME
        if isinstance(body, dict):
            self.token_shape = sorted(body)
            token = next((body[n] for n in _TOKEN_NAMES if isinstance(body.get(n), str) and body[n]), None)
            expires_in = body.get("expires_in") or body.get("expiresIn")
            if isinstance(expires_in, (int, float)) and expires_in > 120:
                lifetime = min(_DEFAULT_LIFETIME, expires_in - 60)
        elif isinstance(body, str) and body:
            self.token_shape = ["<string>"]
            token = body
        elif response.text.strip():
            self.token_shape = ["<text>"]
            token = response.text.strip()
        if not token:
            raise PersonalApiError("Token request answered 200 but no token was found in the answer.")
        self._token = token
        self._expires_at = self._clock() + lifetime
        return token

    def token(self, force: bool = False) -> str:
        if force or not self._token or self._clock() >= self._expires_at:
            return self._fetch_token()
        return self._token

    def get(self, path: str, params: Optional[dict] = None):
        """GET one Personal API path. Returns (status code, parsed JSON or text). A 401 gets one retry with
        a fresh token."""
        url = BASE_URL + "/" + path.lstrip("/")
        params = {k: v for k, v in (params or {}).items() if v is not None}
        for attempt in (1, 2):
            response = self._session.get(
                url, params=params, headers={"Authorization": f"Bearer {self.token(force=attempt == 2)}"}, timeout=60
            )
            if response.status_code != 401 or attempt == 2:
                break
        try:
            body = response.json()
        except ValueError:
            body = self._scrub(response.text)
        return response.status_code, body
