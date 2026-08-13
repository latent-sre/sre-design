"""Reporting: turn the validated KB into a ranked, actionable SRE risk digest."""

from sre_kb.reporting.findings import (
    collect_findings,
    graduation_findings,
    render_md,
    render_text,
)
from sre_kb.reporting.narrative import (
    NARRATIVE_REL,
    NarrativeCheck,
    allowed_refs,
    narrative_brief,
    render_narrative,
    validate_narrative,
)
from sre_kb.reporting.human_report import build_human_report, render_human_report

__all__ = [
    "NARRATIVE_REL",
    "NarrativeCheck",
    "allowed_refs",
    "build_human_report",
    "collect_findings",
    "graduation_findings",
    "narrative_brief",
    "render_md",
    "render_human_report",
    "render_narrative",
    "render_text",
    "validate_narrative",
]
