"""Security: secret scanning gate (the PR is the main exfil path) + helpers."""

from sre_kb.security.secret_scan import (
    SecretLeakError,
    enforce_secret_gate,
    scan_text,
    scan_tree,
)

__all__ = ["SecretLeakError", "enforce_secret_gate", "scan_text", "scan_tree"]
