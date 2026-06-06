"""Output safety lint: flag dangerous patterns in generated artifacts (defends against
prompt-injection-poisoned content reaching a runbook/skill). A hit downgrades the
artifact to needs-review so a human reviews it before it can be executed."""

from __future__ import annotations

import json
import re

_DANGEROUS: list[tuple[str, re.Pattern]] = [
    ("shell-pipe-to-network", re.compile(r"(?i)\b(curl|wget)\b[^|\n]*\|\s*(bash|sh)\b")),
    ("rm-rf", re.compile(r"(?i)\brm\s+-rf?\b")),
    ("disable-tls", re.compile(
        r"(?i)(verify\s*=\s*false|insecure[- ]?skip[- ]?tls|trust[- ]?all|sslverify\s*=\s*false|disable\w*\s*ssl)"
    )),
    ("disable-auth", re.compile(r"(?i)(permitall\s*\(\)|disable\w*auth|anonymous\s+admin)")),
    ("dynamic-eval", re.compile(r"(?i)\b(eval|exec)\s*\(")),
]


def lint_doc(doc: dict) -> list[str]:
    """Return the names of dangerous patterns found in the artifact's spec ([] = clean)."""
    text = json.dumps(doc.get("spec", {}))
    return [name for name, pat in _DANGEROUS if pat.search(text)]
