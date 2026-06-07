"""Service discovery + a fan-out-capped, resumable scan plan (DEEP-COMPARISON R8).

A monorepo can hold many deployable services (one per PCF manifest / application). Discovery finds
them; the plan refuses to fan out beyond `scan.max_services` *before* any artifacts are produced; and
a per-service checkpoint lets an interrupted run resume by service instead of rescanning everything.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from sre_kb.collectors.base import _SKIP_DIRS
from sre_kb.config import load_config

DEFAULT_MAX_SERVICES = 50
CHECKPOINT_REL = "scan-checkpoint.json"


class ScanFanOutError(Exception):
    """Raised when discovery finds more services than the fan-out cap allows — stop before mass output."""


@dataclass(frozen=True)
class Service:
    name: str
    path: Path


def _manifest_services(manifest: Path) -> list[Service]:
    """The service(s) a PCF manifest declares: one per `applications[].name`, rooted at its dir; a
    nameless/unparseable manifest falls back to the directory name."""
    try:
        doc = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return [Service(manifest.parent.name, manifest.parent)]
    apps = doc.get("applications") if isinstance(doc, dict) else None
    names = (
        [str(a["name"]) for a in apps if isinstance(a, dict) and a.get("name")]
        if isinstance(apps, list)
        else []
    )
    return [Service(n, manifest.parent) for n in (names or [manifest.parent.name])]


def discover_services(root: Path) -> list[Service]:
    """Discover deployable services under `root`: one per PCF-manifest application (manifest.yml /
    manifest.yaml), named from the manifest and rooted at its directory. A repo with no manifest is a
    single service rooted at `root`. Stable order, de-duplicated by name; skip-dirs are ignored."""
    root = Path(root)
    found: list[Service] = []
    seen: set[str] = set()
    for manifest in sorted(root.rglob("manifest.y*ml")):
        if any(part in _SKIP_DIRS for part in manifest.relative_to(root).parts):
            continue
        for svc in _manifest_services(manifest):
            if svc.name not in seen:
                seen.add(svc.name)
                found.append(svc)
    return found or [Service(root.name, root)]


def plan_services(root: Path, *, max_services: int | None = None) -> list[Service]:
    """Discover services and enforce the fan-out cap (`scan.max_services`) before any scan runs."""
    cap = (
        max_services
        if max_services is not None
        else (load_config().get("scan") or {}).get("max_services", DEFAULT_MAX_SERVICES)
    )
    services = discover_services(root)
    if cap is not None and len(services) > cap:
        raise ScanFanOutError(
            f"discovered {len(services)} services, exceeding scan.max_services={cap} — refusing to "
            "fan out before any artifacts are produced (a runaway monorepo scan must be capped)"
        )
    return services


def load_done(checkpoint: Path) -> set[str]:
    """The set of services already scanned, from a checkpoint file (missing/corrupt -> empty)."""
    if not checkpoint.is_file():
        return set()
    try:
        return set((json.loads(checkpoint.read_text(encoding="utf-8")) or {}).get("done") or [])
    except (json.JSONDecodeError, OSError):
        return set()


def mark_done(checkpoint: Path, name: str) -> None:
    done = load_done(checkpoint)
    done.add(name)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text(json.dumps({"done": sorted(done)}, indent=2), encoding="utf-8")


def pending(services: list[Service], done: set[str]) -> list[Service]:
    return [s for s in services if s.name not in done]


def run_plan(
    root: Path,
    *,
    work_root: str = ".work",
    run_id: str | None = None,
    to_stage: str = "validate",
    max_services: int | None = None,
) -> dict:
    """Scan each discovered service through the standard pipeline, checkpointing after each so an
    interrupted run resumes by service. Returns a summary; raises ScanFanOutError over the cap."""
    import time

    from sre_kb.pipeline import run

    run_id = run_id or "plan-" + time.strftime("%Y%m%d-%H%M%S")
    services = plan_services(root, max_services=max_services)
    checkpoint = Path(work_root) / run_id / CHECKPOINT_REL
    done = load_done(checkpoint)
    scanned: list[str] = []
    for svc in pending(services, done):
        run(str(svc.path), work_root=work_root, run_id=f"{run_id}-{svc.name}", to_stage=to_stage)
        mark_done(checkpoint, svc.name)
        scanned.append(svc.name)
    return {
        "run_id": run_id,
        "services": [s.name for s in services],
        "scanned": scanned,
        "skipped": sorted(done),
        "checkpoint": str(checkpoint),
    }
