"""Reporting: turn the validated KB into a ranked, actionable SRE risk digest."""

from sre_kb.reporting.findings import collect_findings, render_md, render_text

__all__ = ["collect_findings", "render_md", "render_text"]
