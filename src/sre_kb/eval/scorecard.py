"""Extraction scorecard (HYBRID-PLAN S5) — generalize gap precision/recall to *all* extraction.

`validation/copilot_gap.py` measures one area (the gap-finder) against a per-target truth set. This
generalizes that to the whole engine: run the deterministic pipeline over a *labeled* fixture and
score every produced artifact and detector against the expected set, per area (kind) and per detector.
The §4 coverage matrix + the SRE rubric *are* the spec; this turns them into numbers.

The engine still never calls a model — this measures the deterministic output. Tier-B rows will score
structurally lower (they land `needs-review`, never `verified`); that's expected, not a bug. The
labeled truth file (`<fixture>/.sre/eval-truth.json`) records what a correct scan should extract:

    {"service": "order-service",
     "artifacts": [{"kind": "Flow", "name": "create-order"}, ...],
     "detectors": ["java_spring.annotations", "java_spring.messaging", ...]}

Both `artifacts` and `detectors` are optional — a fixture can label just the areas it exercises.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from sre_kb.pipeline import run as run_pipeline
from sre_kb.workspace import RunLayout

type ArtifactKey = tuple[str, str]  # (kind, name)


def _pr(matched: int, produced: int, expected: int) -> dict[str, float | None]:
    return {
        "recall": (matched / expected) if expected else None,
        "precision": (matched / produced) if produced else None,
    }


@dataclass
class EvalTruth:
    service: str | None
    artifacts: set[ArtifactKey]
    detectors: set[str]


def load_eval_truth(path: str | Path) -> EvalTruth:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    arts = {
        (str(a["kind"]), str(a["name"]))
        for a in (data.get("artifacts") or [])
        if isinstance(a, dict) and a.get("kind") and a.get("name")
    }
    dets = {str(d) for d in (data.get("detectors") or []) if d}
    return EvalTruth(service=data.get("service"), artifacts=arts, detectors=dets)


@dataclass
class Scorecard:
    target: str
    expected_artifacts: set[ArtifactKey]
    produced_artifacts: set[ArtifactKey]
    status_by_artifact: dict[ArtifactKey, str]
    expected_detectors: set[str]
    fired_detectors: set[str]

    # --- artifact (per-area) metrics ---
    def _by_kind(self, keys: set[ArtifactKey]) -> dict[str, set[str]]:
        out: dict[str, set[str]] = defaultdict(set)
        for kind, name in keys:
            out[kind].add(name)
        return out

    def per_area(self) -> dict[str, dict[str, Any]]:
        """Per-kind precision/recall — only over kinds the truth labels (a labeled kind is assumed
        labeled *exhaustively*, so an extra artifact of it is a real false positive). Unlabeled kinds
        are out of scope, never penalized — partial labeling is honest, not a precision hit."""
        exp, prod = self._by_kind(self.expected_artifacts), self._by_kind(self.produced_artifacts)
        rows: dict[str, dict[str, Any]] = {}
        for kind in sorted(exp):
            e, p = exp[kind], prod.get(kind, set())
            matched = e & p
            rows[kind] = {
                "expected": sorted(e),
                "produced": sorted(p),
                "matched": len(matched),
                "missed": sorted(e - p),
                "unexpected": sorted(p - e),
                **_pr(len(matched), len(p), len(e)),
                "verified": sum(1 for n in p if self.status_by_artifact.get((kind, n)) == "verified"),
            }
        return rows

    def _produced_in_scope(self) -> set[ArtifactKey]:
        """Produced artifacts of a labeled kind (the precision denominator) — unlabeled kinds excluded."""
        labeled_kinds = {k for k, _ in self.expected_artifacts}
        return {(k, n) for (k, n) in self.produced_artifacts if k in labeled_kinds}

    def detector_coverage(self) -> dict[str, Any]:
        exp, fired = self.expected_detectors, self.fired_detectors
        return {
            "expected": sorted(exp),
            "fired": sorted(fired),
            "missing": sorted(exp - fired),
            "recall": (len(exp & fired) / len(exp)) if exp else None,
        }

    def overall(self) -> dict[str, Any]:
        e, in_scope = self.expected_artifacts, self._produced_in_scope()
        matched = len(e & in_scope)
        return {
            "artifactCount": len(self.produced_artifacts),
            "expectedCount": len(e),
            "inScopeProduced": len(in_scope),
            **_pr(matched, len(in_scope), len(e)),
            "detectorRecall": self.detector_coverage()["recall"],
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "overall": self.overall(),
            "perArea": self.per_area(),
            "detectorCoverage": self.detector_coverage(),
        }


def _collect_run(layout: RunLayout) -> tuple[set[ArtifactKey], dict[ArtifactKey, str], set[str]]:
    produced: set[ArtifactKey] = set()
    status: dict[ArtifactKey, str] = {}
    for p in layout.kb.rglob("*.yaml"):
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        key = (doc["kind"], doc["metadata"]["name"])
        produced.add(key)
        status[key] = doc.get("status", "needs-review")
    detectors: set[str] = set()
    facts_path = layout.facts / "facts.jsonl"
    if facts_path.exists():
        for line in facts_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                detectors.add(json.loads(line)["evidence"]["detector"])
    return produced, status, detectors


def score_target(
    target: str | Path,
    truth: EvalTruth,
    *,
    work_root: str | Path = ".work",
    run_id: str = "eval",
) -> Scorecard:
    """Run the deterministic pipeline over `target` and score its output against `truth`."""
    run_pipeline(str(target), work_root=str(work_root), run_id=run_id, to_stage="validate")
    layout = RunLayout(Path(work_root), run_id)
    produced, status, detectors = _collect_run(layout)
    return Scorecard(
        target=str(target),
        expected_artifacts=truth.artifacts,
        produced_artifacts=produced,
        status_by_artifact=status,
        expected_detectors=truth.detectors,
        fired_detectors=detectors,
    )
