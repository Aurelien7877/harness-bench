"""Lightweight, offline publication gate for tracked files and reachable Git history.

This pattern scan is a release check, not proof that every secret format is absent.
It does not assess dependency vulnerabilities, GitHub artifacts, or local stashes.
No matching content or credential value is printed.
"""
import argparse
import gzip
import io
import json
import re
import subprocess
from pathlib import Path, PurePosixPath

MAX_BYTES = 4_000_000
RULES = {
    "private_key": rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----",
    "provider_token": rb"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|(?:AKIA|ASIA)[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{35}|xox[baprs]-[A-Za-z0-9-]{20,})",
    "jwt": rb"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}",
    "credential_url": rb"https?://[^\s/@:]+:[^\s/@]+@",
    "private_path": rb"/(?:Users|home)/[A-Za-z0-9_.-]+",
    "private_ip": rb"\b(?:10\.(?:[0-9]{1,3}\.){2}[0-9]{1,3}|192\.168\.[0-9]{1,3}\.[0-9]{1,3}|172\.(?:1[6-9]|2[0-9]|3[01])\.[0-9]{1,3}\.[0-9]{1,3})\b",
}
EMAIL = re.compile(rb"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
SAFE_EMAIL_DOMAINS = {b"example.com", b"example.org", b"example.net", b"users.noreply.github.com", b"noreply.github.com"}
RUNTIME_PARTS = {"runs", ".venv", ".cache", ".home", "__pycache__", ".pytest_cache", ".ssh"}
PRIVATE_FILES = {"auth.json", "credentials.json", "id_rsa", "id_ed25519", ".netrc", ".npmrc", ".pypirc"}


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)


def forbidden_path(path):
    parts = PurePosixPath(path).parts
    name = PurePosixPath(path).name
    return (bool(RUNTIME_PARTS.intersection(parts)) or name in PRIVATE_FILES
            or name == ".env" or (name.startswith(".env.") and name != ".env.example")
            or name.endswith((".pem", ".key", ".p12", ".pfx")))


def inspect_content(content, path):
    """Return rule/count pairs without retaining or returning matched values."""
    issues = []
    if len(content) > MAX_BYTES:
        return [("oversized_blob_requires_review", 1)]
    if path.endswith(".gz"):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(content)) as source:
                content = source.read(MAX_BYTES + 1)
        except (OSError, EOFError):
            return [("invalid_gzip", 1)]
        if len(content) > MAX_BYTES:
            return [("oversized_expansion_requires_review", 1)]
    if b"\x00" in content:
        return [("binary_requires_review", 1)]
    for rule, pattern in RULES.items():
        count = len(re.findall(pattern, content))
        if count:
            issues.append((rule, count))
    private_emails = sum(m.group(1).lower() not in SAFE_EMAIL_DOMAINS for m in EMAIL.finditer(content))
    if private_emails:
        issues.append(("private_email", private_emails))
    if path.endswith(".svg"):
        # A repository banner needs only local vector data and fragment references.
        active = re.findall(rb"<\s*(?:[A-Za-z_][A-Za-z0-9_.-]*:)?(?:script|foreignObject)\b|\bon[a-z]+\s*=", content, re.I)
        external = re.findall(rb"\b(?:href|src)\s*=\s*[\"'](?!#)|url\(\s*[\"']?(?!#)[^\s)\"']", content, re.I)
        if active:
            issues.append(("svg_active_content", len(active)))
        if external:
            issues.append(("svg_nonlocal_resource", len(external)))
    if path.endswith(".ipynb"):
        try:
            notebook = json.loads(content)
            count = sum(bool(c.get("outputs")) or c.get("execution_count") is not None
                        for c in notebook["cells"])
            if count:
                issues.append(("notebook_execution_output", count))
            if notebook.get("metadata", {}).get("widgets"):
                issues.append(("notebook_widget_state", 1))
        except (ValueError, KeyError, TypeError, AttributeError):
            issues.append(("invalid_notebook", 1))
    return issues


def scan_repository(root):
    root = Path(root).resolve()
    findings = []

    def add(source, path, issues, blob=None):
        for rule, count in issues:
            item = {"source": source, "path": path, "rule": rule, "count": count}
            if blob:
                item["blob"] = blob
            findings.append(item)

    paths = [p.decode() for p in git(root, "ls-files", "-z").split(b"\0") if p]
    for path in paths:
        target = root / path
        if forbidden_path(path):
            add("worktree", path, [("tracked_private_or_runtime_file", 1)])
        if target.is_symlink():
            add("worktree", path, [("symlink_requires_review", 1)])
        elif target.is_file():
            add("worktree", path, [("oversized_blob_requires_review", 1)]
                if target.stat().st_size > MAX_BYTES else inspect_content(target.read_bytes(), path))
        else:
            add("worktree", path, [("missing_tracked_file", 1)])

    # Stashes/reflogs and unreachable objects are not published by a normal push.
    refs = git(root, "for-each-ref", "--format=%(refname)", "refs/heads", "refs/tags", "refs/remotes").decode().splitlines()
    objects = git(root, "rev-list", "--objects", *refs).decode().splitlines() if refs else []
    names = {}
    for line in objects:
        sha, _, path = line.partition(" ")
        if path:
            names.setdefault(sha, path)
    # Query sizes first so accidentally tracked model weights do not fill RAM.
    metadata = subprocess.run(["git", "-C", str(root), "cat-file", "--batch-check"],
                              input="".join(sha + "\n" for sha in names).encode(),
                              capture_output=True, check=True).stdout.decode().splitlines()
    small = []
    blobs = 0
    for line in metadata:
        sha, kind, length = line.split()
        if kind != "blob":
            continue
        blobs += 1
        if int(length) > MAX_BYTES:
            add("history", names[sha], [("oversized_blob_requires_review", 1)], sha)
        else:
            small.append(sha)
    # Inspect path history separately: Git may assign a shared blob only one name.
    changed_paths = git(root, "log", "--format=", "--name-only", *refs).decode().splitlines() if refs else []
    for path in sorted(set(changed_paths)):
        if path and forbidden_path(path):
            add("history", path, [("tracked_private_or_runtime_file", 1)])
    request = "".join(sha + "\n" for sha in small).encode()
    batch = subprocess.run(["git", "-C", str(root), "cat-file", "--batch"],
                           input=request, capture_output=True, check=True).stdout
    offset = 0
    for _ in small:
        end = batch.index(b"\n", offset)
        sha, kind, length = batch[offset:end].decode().split()
        size = int(length)
        content = batch[end + 1:end + 1 + size]
        offset = end + 2 + size
        add("history", names[sha], inspect_content(content, names[sha]), sha)
    commits = git(root, "log", "--format=%H%x00%ae%x00%ce", *refs).decode().splitlines() if refs else []
    for record in commits:
        sha, author, committer = record.split("\0")
        for role, email in (("author", author), ("committer", committer)):
            domain = email.partition("@")[2].lower().encode()
            if domain not in SAFE_EMAIL_DOMAINS and domain not in (b"local", b"localhost", b""):
                add("commit_metadata", role, [("private_email", 1)], sha)
    messages = git(root, "log", "--format=%H%x00%B%x00", *refs).split(b"\0") if refs else []
    for index in range(0, len(messages) - 1, 2):
        sha = messages[index].strip().decode()
        add("commit_message", "message", inspect_content(messages[index + 1], "commit-message.txt"), sha)
    return {
        "passed": not findings,
        "scope": "tracked worktree, reachable branch/tag/remote refs, commit messages and email metadata",
        "limits": "Pattern-based offline scan. Excludes stashes, unreachable objects, GitHub artifacts and dependency vulnerabilities. Untracked files are never publication inputs.",
        "tracked_files": len(paths), "reachable_refs": refs, "commits": len(commits),
        "history_blobs": blobs, "findings": findings,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        report = scan_repository(args.root)
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        # A broken scan fails closed, without printing subprocess output or data.
        report = {"passed": False, "scan_error": type(error).__name__}
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
