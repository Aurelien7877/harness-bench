"""Publication gate regressions using generated dummy secrets in temporary Git repos."""
import json
import subprocess

from scripts.check_publication import forbidden_path, inspect_content, scan_repository


def test_content_rules_never_return_secret_values():
    token = b"sk-" + b"dummy" * 8
    personal = b"/" + b"Users/" + b"someone/private.txt"
    issues = inspect_content(token + b"\n" + personal, "example.txt")
    assert {rule for rule, _ in issues} == {"provider_token", "private_path"}
    assert token.decode() not in json.dumps(issues)


def test_notebook_outputs_are_rejected_even_without_a_known_secret():
    notebook = {"cells": [{"outputs": [{"text": "private experiment"}], "execution_count": 1}]}
    assert ("notebook_execution_output", 1) in inspect_content(json.dumps(notebook).encode(), "demo.ipynb")
    notebook["cells"][0].update(outputs=[], execution_count=None)
    assert inspect_content(json.dumps(notebook).encode(), "demo.ipynb") == []


def test_scanner_flags_runtime_files_and_respects_synthetic_fixture_text():
    assert forbidden_path("runs/campaign/manifest.json")
    assert forbidden_path("private/.env")
    assert forbidden_path("private/auth.json")
    assert not forbidden_path(".env.example")
    assert not forbidden_path("scripts/check_publication.py")
    assert inspect_content(b"export API_KEY=YOUR_API_KEY", ".env.example") == []


def test_deleted_secret_in_history_still_blocks_release(tmp_path):
    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)
    git("init")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    secret = b"ghp_" + b"dummy" * 8
    (tmp_path / "old.txt").write_bytes(secret)
    git("add", "old.txt")
    git("commit", "-m", "fixture")
    git("rm", "old.txt")
    git("commit", "-m", "remove fixture")
    (tmp_path / "readme.txt").write_text("safe")
    git("add", "readme.txt")
    git("commit", "-m", "safe current tree")
    report = scan_repository(tmp_path)
    assert not report["passed"]
    assert any(f["source"] == "history" and f["rule"] == "provider_token" for f in report["findings"])
    assert secret.decode() not in json.dumps(report)


def test_untracked_private_files_are_not_published(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / ".env").write_text("private local settings")
    report = scan_repository(tmp_path)
    assert report["passed"] and report["tracked_files"] == 0


def test_large_or_invalid_compressed_content_fails_closed():
    from scripts.check_publication import MAX_BYTES
    assert inspect_content(b"x" * (MAX_BYTES + 1), "large.txt") == [("oversized_blob_requires_review", 1)]
    assert inspect_content(b"not gzip", "archive.gz") == [("invalid_gzip", 1)]


def test_commit_message_secret_blocks_release(tmp_path):
    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)
    git("init")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    (tmp_path / "safe.txt").write_text("safe")
    git("add", "safe.txt")
    secret = "ghp_" + "dummy" * 8
    git("commit", "-m", "accidental message " + secret)
    report = scan_repository(tmp_path)
    assert not report["passed"]
    assert any(f["source"] == "commit_message" and f["rule"] == "provider_token" for f in report["findings"])
    assert secret not in json.dumps(report)


def test_svg_only_allows_local_vector_resources():
    assert inspect_content(b'<svg><g clip-path="url(#safe)"><use href="#shape"/></g></svg>', "banner.svg") == []
    assert ("svg_active_content", 1) in inspect_content(b'<svg><script>alert(1)</script></svg>', "banner.svg")
    assert ("svg_nonlocal_resource", 1) in inspect_content(b'<svg><image href="https://example.com/file"/></svg>', "banner.svg")
