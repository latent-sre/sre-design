"""Engine-owned clobber-protection on publish (HYBRID-PLAN Round-3 R4).

A re-publish must never silently revert an operator's edit to a generated file. `merge_tree` does a
manifest-backed 3-way merge against the target repo; the GitHub forge runs it on the cloned target.
"""

from __future__ import annotations

from pathlib import Path

from sre_kb.publish.forge.github import GitHubForge
from sre_kb.publish.manifest import content_hash, dump_manifest, load_manifest, merge_tree


def _tree(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


# --------------------------------------------------------------------------- merge_tree (unit)


def test_merge_tree_skips_symlinks(tmp_path):
    """A symlink in the staged tree is not followed/copied (consistent with the secret scanner)."""
    staged, dest = tmp_path / "staged", tmp_path / "dest"
    staged.mkdir()
    (staged / "real.txt").write_text("x\n", encoding="utf-8")
    (staged / "link.txt").symlink_to(staged / "real.txt")
    res = merge_tree(staged, dest)
    assert "real.txt" in res.written
    assert "link.txt" not in res.written
    assert not (dest / "link.txt").exists()


def test_first_publish_writes_all_and_records_a_manifest(tmp_path):
    staged, dest = tmp_path / "staged", tmp_path / "dest"
    _tree(staged, {"catalog/a.yaml": "a\n", "catalog/b.yaml": "b\n"})
    res = merge_tree(staged, dest)
    assert set(res.written) == {"catalog/a.yaml", "catalog/b.yaml"}
    assert not res.proposed and not res.removed
    assert (dest / "catalog/a.yaml").read_text() == "a\n"
    assert set(load_manifest(dest)) == {"catalog/a.yaml", "catalog/b.yaml"}


def test_unchanged_file_is_refreshed_not_proposed(tmp_path):
    staged, dest = tmp_path / "staged", tmp_path / "dest"
    _tree(staged, {"catalog/a.yaml": "a\n"})
    merge_tree(staged, dest)  # first publish
    res = merge_tree(staged, dest)  # re-publish, the live file still matches what we wrote
    assert res.written == ["catalog/a.yaml"] and not res.proposed and not res.removed


def test_operator_edit_is_preserved_and_the_draft_is_proposed(tmp_path):
    staged, dest = tmp_path / "staged", tmp_path / "dest"
    _tree(staged, {"catalog/a.yaml": "v1\n"})
    merge_tree(staged, dest)  # publish v1
    (dest / "catalog/a.yaml").write_text("operator tuned\n", encoding="utf-8")  # operator edits it
    _tree(staged, {"catalog/a.yaml": "v2\n"})  # engine now wants v2
    res = merge_tree(staged, dest)
    assert res.proposed == ["catalog/a.yaml"] and res.written == []
    assert (dest / "catalog/a.yaml").read_text() == "operator tuned\n"  # live edit preserved
    assert (dest / ".proposed/catalog/a.yaml").read_text() == "v2\n"  # draft offered alongside
    # the manifest keeps the original hash, so the divergence keeps being detected on later runs
    assert load_manifest(dest)["catalog/a.yaml"] != content_hash(dest / "catalog/a.yaml")


def test_orphaned_output_is_pruned(tmp_path):
    staged, dest = tmp_path / "staged", tmp_path / "dest"
    _tree(staged, {"catalog/a.yaml": "a\n", "catalog/old.yaml": "old\n"})
    merge_tree(staged, dest)  # publish both
    (staged / "catalog/old.yaml").unlink()  # engine stops producing old.yaml
    res = merge_tree(staged, dest)
    assert res.removed == ["catalog/old.yaml"]
    assert not (dest / "catalog/old.yaml").exists()
    assert "catalog/old.yaml" not in load_manifest(dest)


def test_operator_edited_orphan_is_left_in_place(tmp_path):
    staged, dest = tmp_path / "staged", tmp_path / "dest"
    _tree(staged, {"catalog/a.yaml": "a\n", "catalog/old.yaml": "old\n"})
    merge_tree(staged, dest)
    (dest / "catalog/old.yaml").write_text("operator kept this\n", encoding="utf-8")
    (staged / "catalog/old.yaml").unlink()  # engine stops producing it, but a human edited it
    res = merge_tree(staged, dest)
    assert "catalog/old.yaml" not in res.removed
    assert (dest / "catalog/old.yaml").read_text() == "operator kept this\n"


# --------------------------------------------------------------------------- wired into the forge


def test_forge_publish_preserves_operator_edit_and_prunes_orphan(tmp_path):
    staged = tmp_path / "staged"
    _tree(staged, {"catalog/keep.yaml": "new\n", "catalog/edited.yaml": "draft\n"})
    snapshot: dict[str, str] = {}

    def runner(cmd: list[str]) -> str:
        if "clone" in cmd:  # simulate the target repo state we clone into
            work = Path(cmd[-1])
            _tree(
                work,
                {
                    "catalog/keep.yaml": "new\n",  # matches the manifest -> refreshed
                    "catalog/edited.yaml": "OPERATOR\n",  # diverged from the manifest -> proposed
                    "catalog/orphan.yaml": "gone\n",  # not produced anymore -> pruned
                },
            )
            dump_manifest(
                work,
                {
                    "catalog/keep.yaml": content_hash(work / "catalog/keep.yaml"),
                    "catalog/edited.yaml": "sha256:" + "0" * 64,  # != live -> divergence
                    "catalog/orphan.yaml": content_hash(work / "catalog/orphan.yaml"),
                },
            )
        if cmd[-2:] == ["add", "-A"]:  # snapshot the merged tree before the tempdir is cleaned up
            base = Path(cmd[2])
            snapshot.update(
                {
                    str(p.relative_to(base)).replace("\\", "/"): p.read_text()
                    for p in base.rglob("*")
                    if p.is_file()
                }
            )
        if "rev-parse" in cmd:
            return "main\n"
        if "--porcelain" in cmd:
            return " M catalog/keep.yaml\n"
        return ""

    forge = GitHubForge(runner=runner, http_post=lambda *a: {"html_url": "u"}, token="T")
    assert forge.open_pr(staged, sre_repo="o/r", branch="b", title="t", body="x") == "u"

    assert snapshot["catalog/edited.yaml"] == "OPERATOR\n"  # operator edit preserved
    assert snapshot[".proposed/catalog/edited.yaml"] == "draft\n"  # draft offered alongside
    assert "catalog/orphan.yaml" not in snapshot  # orphan pruned
    assert ".sre/manifest.yaml" in snapshot  # manifest persisted for the next run
