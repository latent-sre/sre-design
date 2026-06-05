"""Cross-reference validation (layer c): every crossRef must resolve to an artifact."""

from __future__ import annotations


def check_crossrefs(docs: list[dict]) -> dict[str, list[str]]:
    index = {(d.get("kind"), (d.get("metadata") or {}).get("name")) for d in docs}
    problems: dict[str, list[str]] = {}
    for d in docs:
        name = (d.get("metadata") or {}).get("name")
        errs: list[str] = []
        for ref in d.get("crossRefs") or []:
            rname = ref.get("name")
            if rname in (None, "", "-"):
                continue
            if (ref.get("kind"), rname) not in index:
                errs.append(f"dangling crossRef -> {ref.get('kind')}/{rname}")
        if errs:
            problems[f"{d.get('kind')}/{name}"] = errs
    return problems
