"""Unit tests for scripts/prepush_scan.py (the pre-push personal-data check)"""
import importlib.util
import pathlib
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "prepush_scan.py"
spec = importlib.util.spec_from_file_location("prepush_scan", SCRIPT)
prepush_scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepush_scan)

FAKE_KEY = "Api" + "Key " + "ABCDEFGH" + "12345678"  # built at run time so the file itself does not look like a key

LOG = f"""Add a thing

Some message line
diff --git a/src/a.py b/src/a.py
index 111..222 100644
--- a/src/a.py
+++ b/src/a.py
@@ -1,2 +1,3 @@
 context line with jdoe1234 stays unseen
-removed line with jdoe1234
+added line with jdoe1234 inside
+{FAKE_KEY} in a header
"""


@pytest.fixture
def personal_file(tmp_path):
    f = tmp_path / "patterns.txt"
    f.write_text("# a comment\n\nMFP user name: jdoe1234\nJuh[aá]sz\n", encoding="utf-8")
    return f


def test_the_personal_file_is_parsed_with_labels_and_bare_patterns(personal_file):
    labels = [label for label, _ in prepush_scan.load_patterns(personal_file)]
    assert "MFP user name" in labels and any(label.startswith("personal pattern") for label in labels) and "API key header" in labels


def test_only_added_lines_and_message_lines_count(personal_file):
    lines = list(prepush_scan.relevant(LOG))
    assert ("src/a.py", "added line with jdoe1234 inside") in lines
    assert not any("stays unseen" in text or "removed line" in text for _, text in lines)
    assert ("(commit message)", "Some message line") in lines


def test_hits_name_the_pattern_and_the_file_and_hide_the_match(personal_file):
    hits = prepush_scan.scan(LOG, prepush_scan.load_patterns(personal_file))
    labels = {(label, file) for label, file, _ in hits}
    assert ("MFP user name", "src/a.py") in labels and ("API key header", "src/a.py") in labels
    assert all("jdoe1234" not in snippet and "ABCDEFGH12345678" not in snippet for _, _, snippet in hits)


def test_a_clean_log_has_no_hits(personal_file):
    assert prepush_scan.scan("Fine message\ndiff --git a/x b/x\n+++ b/x\n+nothing special here\n", prepush_scan.load_patterns(personal_file)) == []


def run(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=cwd, capture_output=True, text=True, check=True)


def test_a_real_push_range_is_checked_and_the_hook_is_installed_without_overwriting(tmp_path, personal_file, monkeypatch):
    monkeypatch.setenv("GARMIN_COACH_SCAN_PATTERNS", str(personal_file))
    run(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("harmless\n", encoding="utf-8")
    run(tmp_path, "add", "a.txt")
    run(tmp_path, "commit", "-q", "-m", "first")
    first = run(tmp_path, "rev-parse", "HEAD").stdout.strip()
    (tmp_path / "a.txt").write_text("harmless\nthe user jdoe1234 here\n", encoding="utf-8")
    run(tmp_path, "commit", "-q", "-am", "second")
    second = run(tmp_path, "rev-parse", "HEAD").stdout.strip()
    hits = prepush_scan.check_refs(f"refs/heads/main {second} refs/heads/main {first}\n", cwd=tmp_path)
    assert [(label, file) for label, file, _ in hits] == [("MFP user name", "a.txt")]
    assert prepush_scan.check_refs(f"refs/heads/main {first} refs/heads/main {first}\n", cwd=tmp_path) == []  # nothing new
    assert prepush_scan.check_refs(f"(delete) {'0' * 40} refs/heads/old {first}\n", cwd=tmp_path) == []  # a deleted ref is skipped
    new_branch = prepush_scan.check_refs(f"refs/heads/b {second} refs/heads/b {'0' * 40}\n", cwd=tmp_path)  # no remote yet: everything is new
    assert any(label == "MFP user name" for label, _, _ in new_branch)

    hook = tmp_path / ".git" / "hooks" / "pre-push"
    prepush_scan.install([str(tmp_path)])
    assert hook.exists() and prepush_scan.MARKER in hook.read_text(encoding="utf-8") and "prepush_scan.py" in hook.read_text(encoding="utf-8")
    hook.write_text("#!/bin/sh\necho somebody else's hook\n", encoding="utf-8")
    prepush_scan.install([str(tmp_path)])
    assert "somebody else's hook" in hook.read_text(encoding="utf-8")  # a foreign hook is left alone
