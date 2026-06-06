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
    ("github-fine-grained-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}")),
    ("assigned-secret", re.compile(
        r"(?i)\b(password|passwd|secret|token|api[-_]?key|client[-_]?secret)\b\s*[=:]\s*[\"'][^\"'\s]{6,}[\"']"
    )),
    ("assigned-secret-unquoted", re.compile(
        r"(?i)(password|passwd|secret|token|api[-_]?key|access[-_]?key|client[-_]?secret)\b\s*[=:]\s*([^\s\"';]{8,})"
    )),
    ("jdbc-password", re.compile(r"(?i)jdbc:[^\s\"']*[?&;]password=[^\s\"'&;]{4,}")),
]

# Value-based rules suppressed when the line is obviously a placeholder (a false positive
# here would hard-fail a legitimate publish). Format-strict rules above are never suppressed.
_SUPPRESSIBLE = {"assigned-secret", "assigned-secret-unquoted", "bearer-token", "jdbc-password"}
_PLACEHOLDER = re.compile(
    r"(?i)(your[-_ ]|placeholder|example|change[-_ ]?me|x{4,}|\.\.\.|replace|<[a-z._-]+>|\$\{|\{\{|"
    r"todo|dummy|sample|redacted|\*{3,}|here)"
)


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
            if not pat.search(line):
                continue
            if rule in _SUPPRESSIBLE and _PLACEHOLDER.search(line):
                continue  # obvious placeholder, not a real secret
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


_REDACTION = "***REDACTED***"  # also matches _PLACEHOLDER, so redaction is idempotent


def redact_text(text: str) -> tuple[str, int]:
    """Replace detected secrets with a placeholder, preserving line structure. Returns
    (redacted_text, count). Run before the publish gate (defense-in-depth): scrub first,
    then let the gate verify nothing slipped through."""
    count = 0
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        core, eol = line, ""
        if core.endswith("\r\n"):
            core, eol = core[:-2], "\r\n"
        elif core.endswith("\n"):
            core, eol = core[:-1], "\n"
        suppress = bool(_PLACEHOLDER.search(core))
        for rule, pat in _RULES:
            if rule in _SUPPRESSIBLE and suppress:
                continue
            core, n = pat.subn(_REDACTION, core)
            count += n
        out.append(core + eol)
    return "".join(out), count


def redact_tree(root: Path) -> int:
    """Redact secrets in place from every text file under `root`. Returns total redactions."""
    total = 0
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        if p.stat().st_size > _MAX_FILE_BYTES or not _looks_text(p):
            continue
        redacted, n = redact_text(p.read_text(encoding="utf-8", errors="replace"))
        if n:
            p.write_text(redacted, encoding="utf-8")
            total += n
    return total


def enforce_secret_gate(tree: Path, *, allow: bool = False) -> list[dict]:
    """Scan `tree`; raise SecretLeakError if anything matches (unless allow=True)."""
    findings = scan_tree(tree)
    if findings and not allow:
        raise SecretLeakError(findings)
    return findings
