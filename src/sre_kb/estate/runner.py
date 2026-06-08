"""Run an estate scan across several service repos and validate the estate artifacts."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from sre_kb.collectors import scan
from sre_kb.collectors.base import LOCAL_COMMIT, ScanContext
from sre_kb.config import load_config
from sre_kb.estate.topology import build_estate
from sre_kb.render.diagrams import mermaid_topology
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


def _dump(path: Path, doc: dict) -> None:
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")


def run_estate(targets: list[str], *, work_root: str = ".work", run_id: str | None = None) -> EstateResult:
    cfg = load_config()
    gate = cfg.get("gating", {})
    run_id = run_id or "estate-" + time.strftime("%Y%m%d-%H%M%S")
    layout = RunLayout(Path(work_root), run_id)
    layout.ensure()

    services: list[dict] = []
    roots: dict[str, Path] = {}
    for t in targets:
        root = Path(t).resolve()
        if not root.exists():
            raise FileNotFoundError(f"target not found: {root}")
        ctx = ScanContext(root=root, repo=f"file://{root.name}", commit=LOCAL_COMMIT)
        fs = scan(ctx)
        app = fs.first("pcf.app")
        services.append({"service": app.attrs["name"] if app else root.name, "ctx": ctx, "fs": fs})
        roots[ctx.repo] = root

    docs = build_estate(services)
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
        (diagrams / "topology.mmd").write_text(mermaid_topology(topo), encoding="utf-8")

    svc_names = [s["service"] for s in services]
    report_path = layout.reports / "estate_report.json"
    write_report(report_path, {"run_id": run_id, "services": svc_names, "docs": len(docs),
                               "by_status": by_status, "records": records})
    return EstateResult(run_id, layout.root, svc_names, len(docs), by_status, report_path)
