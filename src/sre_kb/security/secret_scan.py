"""Pattern-based secret scanning. Backs the publish-time gate that hard-fails a PR
containing secrets (defense-in-depth on top of the path:line+hash baseline).

Deterministic regex rules only (no entropy heuristics) to avoid flaky false positives.
"""

from __future__ import annotations

import re
from pathlib import Path

_MAX_FILE_BYTES = 1_000_000

# (rule-name, compiled pattern)
_RULES: list[tuple[str, re.Pattern]] = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("aws-access-key-id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws-secret-access-key", re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*[\"']?[A-Za-z0-9/+=]{40}")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}")),
    ("assigned-secret", re.compile(
        r"(?i)\b(password|passwd|secret|token|api[-_]?key|client[-_]?secret)\b\s*[=:]\s*[\"'][^\"'\s]{6,}[\"']"
    )),
    ("jdbc-password", re.compile(r"(?i)jdbc:[^\s\"']*[?&;]password=[^\s\"'&;]{4,}")),
]


class SecretLeakError(Exception):
    """Raised by the publish-time gate when secrets are present in the PR tree."""

    def __init__(self, findings: list[dict]):
        self.findings = findings
        preview = ", ".join(f"{f['rule']} @ {f['path']}:{f['line']}" for f in findings[:5])
        super().__init__(f"{len(findings)} secret(s) detected in PR tree: {preview}")


def scan_text(text: str, path: str) -> list[dict]:
    findings: list[dict] = []
    for i, line in enumerate(text.splitlines(), 1):
        for rule, pat in _RULES:
            if pat.search(line):
                findings.append({"path": path, "line": i, "rule": rule})
    return findings


def _looks_text(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:2048]
    except OSError:
        return False
    return b"\x00" not in chunk


def scan_tree(root: Path) -> list[dict]:
    findings: list[dict] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        if p.stat().st_size > _MAX_FILE_BYTES or not _looks_text(p):
            continue
        findings += scan_text(p.read_text(encoding="utf-8", errors="replace"), str(p.relative_to(root)))
    return findings


def enforce_secret_gate(tree: Path, *, allow: bool = False) -> list[dict]:
    """Scan `tree`; raise SecretLeakError if anything matches (unless allow=True)."""
    findings = scan_tree(tree)
    if findings and not allow:
        raise SecretLeakError(findings)
    return findings
