"""Diff two sets of KB artifacts on their content signature (kind + spec + status).

Evidence (paths/lines/excerptHash) is deliberately excluded from the signature — it changes on
every re-scan/commit, so including it would report drift for artifacts whose substance is
unchanged. A spec or status change is real drift; evidence churn alone is not."""

from __future__ import annotations

import json
from dataclasses import dataclass

Key = tuple[str, str]


def _key(doc: dict) -> Key:
    return (doc["kind"], doc["metadata"]["name"])


def _norm(doc: dict) -> str:
    """Content signature ignoring volatile fields (evidence bytes, generatedBy)."""
    return json.dumps(
        {"kind": doc["kind"], "spec": doc.get("spec"), "status": doc.get("status")},
        sort_keys=True,
    )


def _has_data_loss(doc: dict) -> bool:
    spec = doc.get("spec", {})
    if doc["kind"] == "BlastRadius":
        return bool((spec.get("stateful") or {}).get("dataLossRisk"))
    if doc["kind"] == "Flow":
        return any(
            fm.get("dataLossRisk")
            for s in spec.get("steps", [])
            for fm in s.get("failureModes", [])
        )
    return False


@dataclass
class KBDiff:
    added: list[Key]
    removed: list[Key]
    changed: list[Key]
    status_changes: list[tuple[Key, str, str]]
    new_data_loss: list[Key]

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


def diff_kb(base: list[dict], head: list[dict]) -> KBDiff:
    b = {_key(d): d for d in base}
    h = {_key(d): d for d in head}
    common = set(b) & set(h)
    added = sorted(set(h) - set(b))
    removed = sorted(set(b) - set(h))
    changed = sorted(k for k in common if _norm(b[k]) != _norm(h[k]))
    status_changes = [
        (k, b[k].get("status", "?"), h[k].get("status", "?"))
        for k in sorted(common)
        if b[k].get("status") != h[k].get("status")
    ]
    new_data_loss = sorted(
        k for k, d in h.items() if _has_data_loss(d) and (k not in b or not _has_data_loss(b[k]))
    )
    return KBDiff(added, removed, changed, status_changes, new_data_loss)


def changelog_md(diff: KBDiff, base_label: str, head_label: str) -> str:
    def fmt(keys: list[Key]) -> list[str]:
        return [f"- `{k[0]}/{k[1]}`" for k in keys] or ["- (none)"]

    lines = [
        "# SRE KB drift",
        "",
        f"**base:** {base_label}  ",
        f"**head:** {head_label}",
        "",
        f"Added: {len(diff.added)} · Removed: {len(diff.removed)} · "
        f"Changed: {len(diff.changed)} · New data-loss risks: {len(diff.new_data_loss)}",
        "",
        "## Added",
        *fmt(diff.added),
        "",
        "## Removed",
        *fmt(diff.removed),
        "",
        "## Changed",
        *fmt(diff.changed),
    ]
    if diff.status_changes:
        lines += ["", "## Status changes"]
        lines += [f"- `{k[0]}/{k[1]}`: {old} → {new}" for k, old, new in diff.status_changes]
    if diff.new_data_loss:
        lines += ["", "## ⚠️ New data-loss risks"]
        lines += fmt(diff.new_data_loss)
    return "\n".join(lines) + "\n"
