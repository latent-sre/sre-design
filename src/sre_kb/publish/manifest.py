"""Engine-owned clobber-protection for the publish path (HYBRID-PLAN Round-3 R4).

A re-publish must never silently revert an operator's edit to a generated file. The engine records
the hash of every file it writes in `.sre/manifest.yaml` in the target repo; on the next publish it
does a 3-way merge against that manifest instead of a blind overwrite:

  * unchanged since we wrote it  -> refresh in place
  * diverged (an operator edit)  -> the new draft is routed to `.proposed/<path>`; the live file is
                                    kept, and the manifest entry is kept so the divergence keeps
                                    being detected on later runs
  * orphaned (we wrote it, no longer produced) -> pruned, unless an operator edited it

Adopted from resiliency-skills' in-tree `assemble`; here it runs against the cloned target repo
inside the forge — the only place the operator's current files exist (our model opens a PR rather
than writing in place). A first publish (no manifest yet) simply writes everything and records it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

MANIFEST_REL = ".sre/manifest.yaml"


def content_hash(path: Path) -> str:
    """Stable content hash of a file's bytes — the keystone of divergence detection."""
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(root: Path) -> dict[str, str]:
    """Read `root/.sre/manifest.yaml` -> {relpath: hash}. A missing/corrupt manifest is treated as
    empty, so a first publish (or a hand-deleted manifest) just re-establishes one."""
    path = root / MANIFEST_REL
    if not path.is_file():
        return {}
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    hashes = doc.get("hashes") if isinstance(doc, dict) else None
    return {str(k): str(v) for k, v in hashes.items()} if isinstance(hashes, dict) else {}


def dump_manifest(root: Path, hashes: dict[str, str]) -> None:
    path = root / MANIFEST_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "apiVersion": "sre.kb/v1alpha1",
                "kind": "PublishManifest",
                "hashes": dict(sorted(hashes.items())),
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


@dataclass
class MergeResult:
    written: list[str] = field(default_factory=list)  # files (over)written with the fresh draft
    proposed: list[str] = field(
        default_factory=list
    )  # operator-edited: new draft routed to .proposed/
    removed: list[str] = field(default_factory=list)  # orphaned AI outputs pruned
    manifest: dict[str, str] = field(default_factory=dict)


def _staged_files(staged: Path) -> list[str]:
    return sorted(
        str(p.relative_to(staged)).replace("\\", "/")
        for p in staged.rglob("*")
        if p.is_file() and not p.is_symlink()
    )


def merge_tree(staged: Path, dest: Path) -> MergeResult:
    """Merge the `staged` tree into `dest` (the target repo working copy) under clobber-protection,
    tracked by `dest/.sre/manifest.yaml`. Returns the changes; the new manifest is written to `dest`."""
    recorded = load_manifest(dest)
    produced = _staged_files(staged)
    res = MergeResult()
    hashes = dict(recorded)
    for rel in produced:
        if rel == MANIFEST_REL:
            continue  # never let a staged file masquerade as the manifest
        src, target = staged / rel, dest / rel
        if target.is_file() and rel in recorded and content_hash(target) != recorded[rel]:
            # an operator edited a file we wrote -> preserve the live file, offer the draft alongside.
            proposed = dest / ".proposed" / rel
            proposed.parent.mkdir(parents=True, exist_ok=True)
            proposed.write_bytes(src.read_bytes())
            res.proposed.append(
                rel
            )  # keep the old recorded hash so divergence keeps being detected
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(src.read_bytes())
            hashes[rel] = content_hash(target)
            res.written.append(rel)
    for rel in sorted(set(recorded) - set(produced)):
        target = dest / rel
        if not target.is_file():
            hashes.pop(rel, None)  # already gone
        elif content_hash(target) == recorded[rel]:
            target.unlink()  # still the AI-written version -> safe to prune
            hashes.pop(rel, None)
            res.removed.append(rel)
        # else: an operator-edited orphan -> leave the file (and its manifest entry) in place
    dump_manifest(dest, hashes)
    res.manifest = hashes
    return res
