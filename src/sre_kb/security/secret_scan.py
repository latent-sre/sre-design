"""Pattern-based secret scanning for the publish-time fail-closed gate."""

from __future__ import annotations

import math
import re
from pathlib import Path

_MAX_FILE_BYTES = 1_000_000
_ENTROPY_MIN_BITS = 4.0
_ENTROPY_MIN_LEN = 20
_SENTINEL_PREFIX = "REPLACE_ME__"

# (rule-name, compiled pattern)
_RULES: list[tuple[str, re.Pattern]] = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("aws-access-key-id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "aws-secret-access-key",
        re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*[\"']?[A-Za-z0-9/+=]{40}"),
    ),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("github-fine-grained-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[0-9A-Za-z_\-]+\.eyJ[0-9A-Za-z_\-]+\.[0-9A-Za-z_\-]+\b")),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}")),
    (
        "uri-with-credentials",
        re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s:/@]+@[^\s/]+", re.I),
    ),
    (
        "assigned-secret",
        re.compile(
            r"(?i)\b(password|passwd|secret|token|api[-_]?key|client[-_]?secret)\b\s*"
            r"[=:]\s*[\"'][^\"'\s]{6,}[\"']"
        ),
    ),
    (
        "assigned-secret-unquoted",
        re.compile(
            r"(?i)(password|passwd|secret|token|api[-_]?key|access[-_]?key|client[-_]?secret)"
            r"\b\s*[=:]\s*([^\s\"';]{8,})"
        ),
    ),
    ("jdbc-password", re.compile(r"(?i)jdbc:[^\s\"']*[?&;]password=[^\s\"'&;]{4,}")),
]

# Value-based rules suppressed when the line is obviously a placeholder. Format-strict rules above
# are never suppressed.
_SUPPRESSIBLE = {"assigned-secret", "assigned-secret-unquoted", "bearer-token", "jdbc-password"}
_PLACEHOLDER = re.compile(
    r"(?i)(your[-_ ]|placeholder|example|change[-_ ]?me|x{4,}|\.\.\.|replace|"
    r"<[a-z._-]+>|\$\{|\{\{|todo|dummy|sample|redacted|\*{3,}|here)"
)
_SECRETISH_MARKERS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "apikey",
    "accesskey",
    "privatekey",
    "clientsecret",
    "credential",
    "connectionstring",
    "connstring",
    "dsn",
)
_OPAQUE_VALUE = re.compile(r"""^['"]?[^\s'"]{12,}['"]?$""")
_TOKEN_RE = re.compile(r"[^\s'\"=:,;()\[\]{}<>]+")
_OPAQUE = re.compile(r"^[A-Za-z0-9+=_-]+$")


class SecretLeakError(Exception):
    """Raised by the publish-time gate when secrets are present in the PR tree."""

    def __init__(self, findings: list[dict]):
        self.findings = findings
        preview = ", ".join(f"{f['rule']} @ {f['path']}:{f['line']}" for f in findings[:5])
        super().__init__(f"{len(findings)} secret(s) detected in PR tree: {preview}")


def _is_secretish_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return any(marker in normalized for marker in _SECRETISH_MARKERS)


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _entropy_candidate(tok: str) -> bool:
    if tok.startswith(_SENTINEL_PREFIX) or len(tok) < _ENTROPY_MIN_LEN:
        return False
    if not _OPAQUE.match(tok):
        return False
    if re.fullmatch(r"[0-9a-fA-F]{32,}", tok):
        return False
    return any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok)


def scan_text(text: str, path: str) -> list[dict]:
    findings: list[dict] = []
    for i, line in enumerate(text.splitlines(), 1):
        for rule, pat in _RULES:
            if not pat.search(line):
                continue
            if rule in _SUPPRESSIBLE and _PLACEHOLDER.search(line):
                continue
            findings.append({"path": path, "line": i, "rule": rule})

        for tok in _TOKEN_RE.findall(line):
            if _entropy_candidate(tok) and _shannon_entropy(tok) >= _ENTROPY_MIN_BITS:
                findings.append({"path": path, "line": i, "rule": "high-entropy"})

        for sep in (":", "="):
            if sep not in line:
                continue
            key, _, value = line.partition(sep)
            value = value.strip()
            if (
                _is_secretish_key(key)
                and value
                and not value.startswith(_SENTINEL_PREFIX)
                and _OPAQUE_VALUE.match(value)
                and not _PLACEHOLDER.search(value)
            ):
                findings.append({"path": path, "line": i, "rule": "value-shape"})
            break

    seen: set[tuple[str, int, str]] = set()
    unique: list[dict] = []
    for finding in findings:
        key = (finding["path"], finding["line"], finding["rule"])
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    return unique


_TEXT_CTRL = frozenset({0x09, 0x0A, 0x0D, 0x0C})  # tab, LF, CR, FF


def _is_binary(data: bytes) -> bool:
    """True for a genuine binary: more than 30% control bytes in the first 8 KB."""
    chunk = data[:8192]
    if not chunk:
        return False
    ctrl = sum(1 for b in chunk if b < 0x20 and b not in _TEXT_CTRL)
    return ctrl / len(chunk) > 0.30


def _decode_for_scan(data: bytes) -> tuple[str, str] | None:
    """Decode bytes to (text, encoding), preserving encoding for redaction write-back."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16"), "utf-16"
        except UnicodeDecodeError:
            pass
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig"), "utf-8-sig"
    if _is_binary(data):
        return None
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("latin-1"), "latin-1"


def _decoded_file(path: Path) -> tuple[str, str] | None:
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    return _decode_for_scan(data)


def scan_tree(root: Path) -> list[dict]:
    findings: list[dict] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        decoded = _decoded_file(p)
        if decoded is not None:
            findings += scan_text(decoded[0], str(p.relative_to(root)))
    return findings


_REDACTION = "***REDACTED***"  # also matches _PLACEHOLDER, so redaction is idempotent


def redact_text(text: str) -> tuple[str, int]:
    """Replace detected regex-pattern secrets with a placeholder, preserving line structure."""
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
    """Redact regex-pattern secrets, writing back in the file's original text encoding."""
    total = 0
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        decoded = _decoded_file(p)
        if decoded is None:
            continue
        text, encoding = decoded
        redacted, n = redact_text(text)
        if n:
            p.write_bytes(redacted.encode(encoding))
            total += n
    return total


def enforce_secret_gate(tree: Path, *, allow: bool = False) -> list[dict]:
    """Scan `tree`; raise SecretLeakError if anything matches (unless allow=True)."""
    findings = scan_tree(tree)
    if findings and not allow:
        raise SecretLeakError(findings)
    return findings
