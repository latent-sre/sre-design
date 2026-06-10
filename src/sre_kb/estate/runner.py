"""Run an estate scan across several service repos and validate the estate artifacts."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from sre_kb.collectors import scan
from sre_kb.collectors.base import LOCAL_COMMIT, ScanContext
from sre_kb.config import load_config
from sre_kb.estate.topology import build_estate, library_version_skew
from sre_kb.render.diagrams import TOPOLOGY_LEGEND, diagram_markdown, mermaid_topology
from sre_kb.util import slug
from sre_kb.validation.gating import final_status
from sre_kb.validation.provenance import verify_evidence_roots
from sre_kb.validation.report import write_report
from sre_kb.validation.structural import validate_doc
from sre_kb.workspace import RunLayout


@dataclass
class EstateResult:
    run_id: str
    root: Path
    services: list[str]
    docs: int
    by_status: dict
    report_path: Path | None = None
    findings: list[dict] | None = None


def _dump(path: Path, doc: dict) -> None:
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")


def run_estate(targets: list[str], *, work_root: str = ".work", run_id: str | None = None,
               internal_namespaces: list[str] | None = None) -> EstateResult:
    cfg = load_config()
    gate = cfg.get("gating", {})
    if internal_namespaces is None:
        internal_namespaces = (cfg.get("estate") or {}).get("internal_namespaces") or []
    run_id = run_id or "estate-" + time.strftime("%Y%m%d-%H%M%S")
    layout = RunLayout(Path(work_root), run_id)
    layout.ensure()

    services: list[dict] = []
    roots: dict[str, Path] = {}
    for t in targets:
        root = Path(t).resolve()
        if not root.exists():
            raise FileNotFoundError(f"target not found: {root}")
        # Repo identity is the full file URI — collision-free by construction, so two targets
        # that share a basename (team-a/api + team-b/api) each verify provenance against their
        # OWN root (the old basename-derived key silently crossed them).
        ctx = ScanContext(root=root, repo=root.as_uri(), commit=LOCAL_COMMIT)
        if ctx.repo in roots:
            continue  # the same target listed twice (shell-glob overlap) is idempotent
        fs = scan(ctx)
        app = fs.first("pcf.app")
        name = (app.attrs.get("name") if app else None) or root.name
        if any(s["service"] == name for s in services):
            name = slug(f"{root.parent.name}-{root.name}")  # same-named services stay distinct nodes
        services.append({"service": name, "ctx": ctx, "fs": fs})
        roots[ctx.repo] = root

    docs = build_estate(services, tuple(internal_namespaces))
    findings = library_version_skew(services, tuple(internal_namespaces))
    layout.reset_kb()  # re-run under the same run-id must not leak stale estate artifacts
    by_status: dict[str, int] = {}
    records = []
    for d in docs:
        struct = validate_doc(d)
        prov = verify_evidence_roots(d, roots)
        status = final_status(
            d,
            structural_ok=not struct,
            provenance_ok=not prov,
            crossref_ok=True,
            min_confidence=gate.get("verified_min_confidence", 0.7),
            require_verified_provenance=gate.get("require_verified_provenance", True),
        )
        d["status"] = status
        out = (layout.reports / "rejected" if status == "rejected" else layout.kb_dir(status)) / d["kind"]
        out.mkdir(parents=True, exist_ok=True)
        _dump(out / f"{d['metadata']['name']}.yaml", d)
        by_status[status] = by_status.get(status, 0) + 1
        records.append(
            {"artifact": f"{d['kind']}/{d['metadata']['name']}", "status": status,
             "structural": struct, "provenance": prov}
        )

    topo = next((d for d in docs if d["kind"] == "Topology"), None)
    if topo:
        diagrams = layout.root / "projections" / "diagrams"
        diagrams.mkdir(parents=True, exist_ok=True)
        src = mermaid_topology(topo)
        (diagrams / "topology.mmd").write_text(src, encoding="utf-8")
        (diagrams / "topology.md").write_text(
            diagram_markdown("estate — topology", src, TOPOLOGY_LEGEND), encoding="utf-8")

    svc_names = [s["service"] for s in services]
    report_path = layout.reports / "estate_report.json"
    write_report(report_path, {"run_id": run_id, "services": svc_names, "docs": len(docs),
                               "by_status": by_status, "records": records, "findings": findings})
    return EstateResult(run_id, layout.root, svc_names, len(docs), by_status, report_path, findings)
