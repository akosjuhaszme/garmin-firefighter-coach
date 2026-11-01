"""
Pre-push check for personal data and secrets (a git pre-push hook).

Look at what a push would publish (the added lines of every commit and the commit messages) and stop the push when something
matches. Two kinds of patterns:
 - generic ones that are built in: API keys, tokens, private key blocks, e-mail addresses, session cookies;
 - personal ones that live OUTSIDE every repository in a file of your own (default ~/.garmin-coach/scan_patterns.txt, or the file
   named by GARMIN_COACH_SCAN_PATTERNS): one regular expression per line, either "label: regex" or just the regex; blank lines and
   lines starting with # are ignored. The patterns themselves are personal (a name, a device number, a user name), so they are
   never committed.

Usage:
  python scripts/prepush_scan.py --install [REPO ...]   put the hook into the given repositories (default: the current one)
  git push                                              the hook runs this script by itself
  git push --no-verify                                  skips the check on purpose

The output names the pattern and the file, with the matching text hidden, so the log does not repeat what it found.
"""
import os
import pathlib
import re
import subprocess
import sys

MARKER = "# prepush_scan (garmin coach)"
GENERIC = {
    "API key header": r"ApiKey [A-Za-z0-9]{8,}",
    "secret-looking key": r"\bsk-[A-Za-z0-9_-]{20,}",
    "GitHub token": r"\bgh[pousr]_[A-Za-z0-9]{20,}",
    "private key block": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "e-mail address": r"[A-Za-z0-9._%+-]+@(?:gmail|outlook|hotmail|icloud|yahoo)\.[A-Za-z]{2,}",
    "session cookie": r"__Secure-next-auth\.session-token\s*[=:]\s*[A-Za-z0-9%._-]{20,}",
}
ZERO = "0" * 40


def patterns_file() -> pathlib.Path:
    return pathlib.Path(os.environ.get("GARMIN_COACH_SCAN_PATTERNS") or (pathlib.Path.home() / ".garmin-coach" / "scan_patterns.txt"))


def load_patterns(path=None) -> list:
    """[(label, compiled regex)] from the built-in list and the personal file"""
    found = [(label, re.compile(rx)) for label, rx in GENERIC.items()]
    path = pathlib.Path(path) if path else patterns_file()
    if path.exists():
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            label, _, rx = line.partition(": ")
            if not rx:
                label, rx = f"personal pattern {number}", line
            found.append((label.strip(), re.compile(rx.strip(), re.IGNORECASE)))
    return found


def relevant(log_output: str):
    """(file, line) for the added lines and the commit message lines of `git log -p`; context and removed lines are skipped"""
    current = "(commit message)"
    for line in log_output.splitlines():
        if line.startswith("diff --git"):
            current = line.rsplit(" b/", 1)[-1]
        elif line.startswith("+++") or line.startswith("---") or line.startswith("@@") or line.startswith("index "):
            continue
        elif line.startswith("+"):
            yield current, line[1:]
        elif line.startswith(("-", " ")):
            continue
        elif line.startswith(("new file mode", "deleted file mode", "old mode", "new mode", "similarity", "rename ", "Binary files")):
            continue
        elif line.strip():
            yield "(commit message)", line


def scan(log_output: str, patterns: list) -> list:
    """[(label, file, masked snippet)], each pattern at most once per file"""
    hits, seen = [], set()
    for file, text in relevant(log_output):
        for label, rx in patterns:
            match = rx.search(text)
            if match and (label, file) not in seen:
                seen.add((label, file))
                masked = (text[:match.start()] + "[...]" + text[match.end():]).strip()
                hits.append((label, file, masked[:100]))
    return hits


def git_log(args: list, cwd=None) -> str:
    done = subprocess.run(["git", "log", "-p", "--no-color", "--format=%B", *args], capture_output=True, cwd=cwd)
    return done.stdout.decode("utf-8", "replace")


def check_refs(stdin_text: str, cwd=None) -> list:
    hits = []
    patterns = load_patterns()
    for line in stdin_text.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[1] == ZERO:  # nothing to scan for a deleted ref
            continue
        local_sha, remote_sha = parts[1], parts[3]
        args = [local_sha, "--not", "--remotes"] if remote_sha == ZERO else [f"{remote_sha}..{local_sha}"]
        hits += scan(git_log(args, cwd), patterns)
    return hits


def install(repos: list) -> None:
    script = pathlib.Path(__file__).resolve().as_posix()
    python = pathlib.Path(sys.executable).resolve().as_posix()
    for repo in repos:
        hooks = pathlib.Path(repo) / ".git" / "hooks"
        if not hooks.is_dir():
            print(f"{repo}: no .git/hooks folder, skipped")
            continue
        hook = hooks / "pre-push"
        if hook.exists() and MARKER not in hook.read_text(encoding="utf-8", errors="replace"):
            print(f"{repo}: another pre-push hook exists, not replaced")
            continue
        hook.write_text(f'#!/bin/sh\n{MARKER}\nexec "{python}" "{script}" "$@"\n', encoding="utf-8", newline="\n")
        print(f"{repo}: hook installed")


def main(argv: list) -> int:
    if argv[:1] == ["--install"]:
        install(argv[1:] or [os.getcwd()])
        return 0
    hits = check_refs(sys.stdin.read())
    if not hits:
        return 0
    print("prepush_scan: the push would publish text that matches a personal-data or secret pattern:", file=sys.stderr)
    for label, file, snippet in hits:
        print(f"  [{label}] {file}: {snippet}", file=sys.stderr)
    print("Nothing was pushed. Remove it (or rewrite the unpushed commits), or push with --no-verify if it is meant to be public.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
