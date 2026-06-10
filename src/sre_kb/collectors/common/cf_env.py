"""cf-env snapshot collector (NEXT-INCREMENTS §4.3): `.sre/cf-env.json` -> `pcf.space` /
`pcf.service-instance` facts.

Developers with space-developer rights run `cf env <app>` and check in a
credential-stripped snapshot. Two shapes are accepted, and ONLY the allowlisted fields are
read from either — credentials never become facts even when a snapshot mistakenly contains
them:

  redacted (preferred):
    {"app": "order-service", "capturedAt": "2026-06-01T12:00:00Z",
     "organization": "acme-org", "space": "prod",
     "services": [{"name": "orders-postgres", "label": "postgres", "plan": "standard",
                   "tags": ["relational"], "managed": true}]}

  raw-ish (pasted `cf env` JSON): VCAP_APPLICATION -> organization_name/space_name,
    VCAP_SERVICES -> per binding name/label/plan/tags
    (managed = label != "user-provided").

Facts carry source="cf-env-snapshot" and the snapshot's capturedAt (when present) as a
freshness marker — snapshot facts drift from live platform state, which is exactly what
`sre-kb diff` exists to catch. The repo-wide secret-scan gate and detect-secrets baseline
cover the file itself.
"""

from __future__ import annotations

import json

from sre_kb.collectors.base import ScanContext, parse_error_fact
from sre_kb.models.facts import Fact, Symbol
from sre_kb.util import find_line

SNAPSHOT_REL = ".sre/cf-env.json"
_DETECTOR = "common.cf_env"


def _maybe_json(value: object) -> object:
    """`cf env` emits VCAP_* as JSON strings inside the JSON document; parse defensively."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def _service_entries(doc: dict) -> list[dict]:
    """The allowlisted per-binding fields from either snapshot shape. Anything not on the
    allowlist — `credentials` above all — is dropped here and never reaches a fact."""
    out: list[dict] = []

    def keep(inst: dict, label: str | None = None) -> None:
        name = inst.get("name")
        if not isinstance(name, str):
            return
        lbl = inst.get("label") if isinstance(inst.get("label"), str) else label
        out.append({
            "name": name,
            "label": lbl,
            "plan": inst.get("plan") if isinstance(inst.get("plan"), str) else None,
            "tags": [t for t in (inst.get("tags") or []) if isinstance(t, str)],
            "managed": bool(inst["managed"]) if isinstance(inst.get("managed"), bool)
            else lbl != "user-provided",
        })

    for inst in doc.get("services") or []:
        if isinstance(inst, dict):
            keep(inst)
    vcap_services = _maybe_json(doc.get("VCAP_SERVICES"))
    if isinstance(vcap_services, dict):
        for label, instances in vcap_services.items():
            for inst in instances if isinstance(instances, list) else []:
                if isinstance(inst, dict):
                    keep(inst, label=str(label))
    return out


def _org_space(doc: dict) -> tuple[str | None, str | None]:
    org, space = doc.get("organization"), doc.get("space")
    vcap_app = _maybe_json(doc.get("VCAP_APPLICATION"))
    if isinstance(vcap_app, dict):
        org = org or vcap_app.get("organization_name")
        space = space or vcap_app.get("space_name")
    return (org if isinstance(org, str) else None,
            space if isinstance(space, str) else None)


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("cf-env.json"):
        rel = ctx.rel(path)
        if rel != SNAPSHOT_REL:
            continue  # the convention is exactly .sre/cf-env.json; stray copies don't count
        lines = ctx.read_lines(rel)
        try:
            doc = json.loads(ctx.read_text(rel)) or {}
        except (json.JSONDecodeError, ValueError) as exc:
            facts.append(parse_error_fact(ctx, rel, _DETECTOR, exc))
            continue
        if not isinstance(doc, dict):
            continue
        captured = doc.get("capturedAt") if isinstance(doc.get("capturedAt"), str) else None
        org, space = _org_space(doc)
        if org or space:
            facts.append(Fact(
                "pcf.space",
                {"organization": org, "space": space, "app": doc.get("app"),
                 "capturedAt": captured, "source": "cf-env-snapshot"},
                ctx.evidence(rel, 1, len(lines), _DETECTOR),
                Symbol(f"{org}/{space}", "pcf-space"),
            ))
        for inst in _service_entries(doc):
            ln = find_line(lines, inst["name"]) or 1
            facts.append(Fact(
                "pcf.service-instance",
                {**inst, "capturedAt": captured, "source": "cf-env-snapshot"},
                ctx.evidence(rel, ln, ln, _DETECTOR),
                Symbol(inst["name"], "pcf-service-instance"),
            ))
    return facts
