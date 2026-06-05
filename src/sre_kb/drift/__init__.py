"""Drift detection: diff a KB across two scans so it stays live, not a one-time snapshot."""

from sre_kb.drift.diff import KBDiff, changelog_md, diff_kb

__all__ = ["KBDiff", "changelog_md", "diff_kb"]
