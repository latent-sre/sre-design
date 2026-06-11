"""Coverage accounting — the engine's "known unknowns", deterministically.

The production expectation the engine previously could not meet: after a run, know not just
what was found, but what was never *looked at* — so the discover-areas loop (the Tier-B
half, `pipeline/areas.py`) starts from a byte-grounded inventory of blind spots instead of
asking an LLM to guess. Three ledgers, all computed from the run itself:

  files     — every file the scan walked vs every file cited by at least one fact
              (a parse-error fact counts as covered: the engine looked and said so);
  kinds     — registered artifact kinds this run never produced;
  detectors — the detector vocabulary that actually fired.
"""

from __future__ import annotations

from collections import Counter, defaultdict

_MAX_GROUPS = 25
_SAMPLES_PER_GROUP = 3


def _group_of(rel: str) -> str:
    """The blind-spot bucket a file belongs to: its extension, else its basename
    (Dockerfile, Jenkinsfile, Makefile and friends are families of their own)."""
    name = rel.rsplit("/", 1)[-1]
    if "." in name[1:]:
        return "*." + name.rsplit(".", 1)[-1].lower()
    return name


def coverage_report(ctx, fs, docs: list[dict]) -> dict:
    """The run's coverage ledger. `ctx` is the scan context (the walked universe respects the
    same skip-dirs/size budgets every collector saw), `fs` the fact set, `docs` the artifacts."""
    from sre_kb.registry import kinds

    walked = [ctx.rel(p) for p in ctx.files("*")]
    covered = {f.evidence.path for f in fs.facts}
    uncovered = [rel for rel in walked if rel not in covered]

    counts: Counter[str] = Counter(_group_of(rel) for rel in uncovered)
    samples: dict[str, list[str]] = defaultdict(list)
    for rel in uncovered:
        bucket = samples[_group_of(rel)]
        if len(bucket) < _SAMPLES_PER_GROUP:
            bucket.append(rel)
    groups = [{"group": g, "count": n, "samples": samples[g]}
              for g, n in counts.most_common(_MAX_GROUPS)]

    kinds_emitted = {d.get("kind") for d in docs}
    return {
        "filesWalked": len(walked),
        "filesCovered": len(walked) - len(uncovered),
        "uncovered": {"count": len(uncovered), "groups": groups},
        "kindsNeverEmitted": sorted(set(kinds()) - kinds_emitted),
        "detectorsFired": sorted({f.evidence.detector for f in fs.facts}),
    }
