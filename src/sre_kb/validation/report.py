"""Validation report writer — nothing is silently dropped; the report is the record."""

from __future__ import annotations

import json
from pathlib import Path


def write_report(path: Path, report: dict) -> None:
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
