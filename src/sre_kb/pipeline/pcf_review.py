"""Tier-B PCF deployment review (NEXT-INCREMENTS §3.2) — the engine half of review-pcf.

The manifest collector proves *what the manifest says*; whether a setting deserves operator
attention is a judgment call (one instance can be correct for a worker, a port health check
can be right for a TCP process). The skill/provider proposes which apps deserve attention;
the engine then re-derives every accepted check **deterministically from the manifest
facts** — a proposal whose condition the bytes don't support is refuted, whatever the
rationale says. Survivors are advisory findings (`source: llm`), never verified artifacts.

Checks (the full vocabulary — an unknown check is dropped, never guessed):
  single-instance     — the app (or its sole web process) runs one instance
  port-health-check   — health-check-type is port/unset while the app serves HTTP routes
  missing-disk-quota  — no disk_quota declared
  env-config-binding  — an env var carries endpoint-shaped config (a URL/URI/host) that
                        belongs in a service binding
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sre_kb.collectors import scan
from sre_kb.collectors.base import LOCAL_COMMIT, ScanContext
from sre_kb.models.facts import Fact

# Conventional location of the skill's output inside the (untrusted) target repo.
PROPOSALS_REL = ".sre/pcf-review-proposals.json"
REVIEW_REL = ".sre/pcf-review.json"

_SEVERITIES = {"high", "medium", "low"}
_ENDPOINT_KEY = ("_URL", "_URI", "_HOST", "_ADDR")


@dataclass(frozen=True)
class PcfProposal:
    check: str
    app: str
    severity: str | None = None
    rationale: str | None = None


@dataclass
class PcfReviewOutcome:
    proposal: PcfProposal
    result: str  # routed | refuted | unknown-check | unknown-app
    note: str = ""
    path: str | None = None


@dataclass
class PcfReviewResult:
    outcomes: list[PcfReviewOutcome] = field(default_factory=list)

    def kept(self) -> list[PcfReviewOutcome]:
        return [o for o in self.outcomes if o.result == "routed"]


def load_proposals(path: Path) -> list[PcfProposal]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for p in (doc.get("proposals") or []) if isinstance(doc, dict) else []:
        if isinstance(p, dict) and p.get("check") and p.get("app"):
            out.append(PcfProposal(str(p["check"]), str(p["app"]),
                                   str(p["severity"]) if p.get("severity") else None,
                                   str(p["rationale"]) if p.get("rationale") else None))
    return out


def _web_instances(attrs: dict) -> object:
    """The instance count that matters for failover: the web process's when one is declared,
    else the app-level count."""
    for p in attrs.get("processes") or []:
        if p.get("type") == "web" and p.get("instances") is not None:
            return p["instances"]
    return attrs.get("instances")


def _rederive(check: str, attrs: dict) -> tuple[bool, str]:
    """The engine's deterministic re-proof of one check against a pcf.app fact. Returns
    (condition holds, note)."""
    if check == "single-instance":
        n = _web_instances(attrs)
        return (n == 1, f"instances={n}")
    if check == "port-health-check":
        hc = (attrs.get("healthCheck") or {}).get("type")
        http_app = bool(attrs.get("routes")) and not attrs.get("noRoute")
        return (http_app and hc in (None, "port"),
                f"health-check-type={hc or 'unset'} routes={len(attrs.get('routes') or [])}")
    if check == "missing-disk-quota":
        return (attrs.get("disk") is None, f"disk_quota={attrs.get('disk')}")
    if check == "env-config-binding":
        hits = sorted(k for k, v in (attrs.get("env") or {}).items()
                      if "://" in str(v) or k.upper().endswith(_ENDPOINT_KEY))
        return (bool(hits), f"endpoint-shaped env var(s): {', '.join(hits) or 'none'}")
    return (False, "unknown check")


def apply_review(apps: list[Fact], proposals: list[PcfProposal]) -> PcfReviewResult:
    by_name: dict[str, Fact] = {}
    for a in apps:  # base manifest first (collector ordering); keep the first per app name
        by_name.setdefault(a.attrs.get("name"), a)
    result = PcfReviewResult()
    for p in proposals:
        if p.check not in {"single-instance", "port-health-check",
                           "missing-disk-quota", "env-config-binding"}:
            result.outcomes.append(PcfReviewOutcome(p, "unknown-check",
                                                    f"'{p.check}' is not in the vocabulary"))
            continue
        app = by_name.get(p.app)
        if app is None:
            result.outcomes.append(PcfReviewOutcome(p, "unknown-app",
                                                    f"no scanned manifest declares app '{p.app}'"))
            continue
        holds, note = _rederive(p.check, app.attrs)
        result.outcomes.append(PcfReviewOutcome(
            p, "routed" if holds else "refuted",
            note if holds else f"manifest disproves it: {note}",
            app.evidence.path,
        ))
    return result


def run_pcf_review(target: str) -> PcfReviewResult:
    """Load proposals from the target, re-derive each against a fresh manifest scan, and write
    the reviewed findings back (`.sre/pcf-review.json`) — advisory, `source: llm`."""
    root = Path(target).resolve()
    ctx = ScanContext(root=root, repo=root.as_uri(), commit=LOCAL_COMMIT)
    apps = scan(ctx).of("pcf.app")
    result = apply_review(apps, load_proposals(root / PROPOSALS_REL))
    findings = [{
        "check": o.proposal.check,
        "app": o.proposal.app,
        "severity": o.proposal.severity if o.proposal.severity in _SEVERITIES else "medium",
        "rationale": o.proposal.rationale,
        "engineNote": o.note,
        "evidence": o.path,
        "source": "llm",
        "advisory": True,
    } for o in result.kept()]
    out = root / REVIEW_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"findings": findings}, indent=2), encoding="utf-8")
    return result
