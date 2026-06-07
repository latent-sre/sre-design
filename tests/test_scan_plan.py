"""DEEP-COMPARISON R8: service discovery + fan-out-capped, resumable scan plan."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from sre_kb.cli import app
from sre_kb.scan_plan import (
    ScanFanOutError,
    Service,
    discover_services,
    load_done,
    mark_done,
    pending,
    plan_services,
    run_plan,
)

runner = CliRunner()


def _manifest(d: Path, name: str) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.yml").write_text(f"applications:\n  - name: {name}\n", encoding="utf-8")


def test_discover_services_from_manifests(tmp_path):
    _manifest(tmp_path / "a", "svc-a")
    _manifest(tmp_path / "b", "svc-b")
    _manifest(tmp_path / "node_modules" / "junk", "junk-svc")  # under a skip-dir -> ignored
    svcs = discover_services(tmp_path)
    assert {s.name for s in svcs} == {"svc-a", "svc-b"}
    assert {s.path for s in svcs} == {tmp_path / "a", tmp_path / "b"}


def test_discover_no_manifest_is_single_root_service(tmp_path):
    (tmp_path / "src").mkdir()
    svcs = discover_services(tmp_path)
    assert len(svcs) == 1 and svcs[0].path == tmp_path and svcs[0].name == tmp_path.name


def test_multi_app_manifest_is_multiple_services(tmp_path):
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "manifest.yml").write_text(
        "applications:\n  - name: app1\n  - name: app2\n", encoding="utf-8"
    )
    assert {s.name for s in discover_services(tmp_path)} == {"app1", "app2"}


def test_fan_out_cap(tmp_path):
    _manifest(tmp_path / "a", "a")
    _manifest(tmp_path / "b", "b")
    with pytest.raises(ScanFanOutError):
        plan_services(tmp_path, max_services=1)
    assert len(plan_services(tmp_path, max_services=5)) == 2


def test_checkpoint_roundtrip_and_pending(tmp_path):
    cp = tmp_path / "scan-checkpoint.json"
    assert load_done(cp) == set()
    mark_done(cp, "svc-a")
    mark_done(cp, "svc-a")  # idempotent
    assert load_done(cp) == {"svc-a"}
    svcs = [Service("svc-a", tmp_path), Service("svc-b", tmp_path)]
    assert [s.name for s in pending(svcs, {"svc-a"})] == ["svc-b"]


def test_run_plan_scans_then_resumes(tmp_path, monkeypatch):
    repo = tmp_path / "mono"
    _manifest(repo / "a", "svc-a")
    _manifest(repo / "b", "svc-b")
    calls: list[str] = []
    monkeypatch.setattr("sre_kb.pipeline.run", lambda target, **kw: calls.append(Path(target).name))
    work = str(tmp_path / "work")

    first = run_plan(repo, work_root=work, run_id="t", to_stage="scan")
    assert sorted(first["scanned"]) == ["svc-a", "svc-b"]
    assert sorted(calls) == ["a", "b"]  # scanned each service's directory

    calls.clear()  # resume: same run_id -> checkpoint says both done -> nothing rescanned
    second = run_plan(repo, work_root=work, run_id="t", to_stage="scan")
    assert second["scanned"] == [] and sorted(second["skipped"]) == ["svc-a", "svc-b"]
    assert calls == []


def test_cli_plan_lists_services(tmp_path):
    _manifest(tmp_path / "a", "svc-a")
    r = runner.invoke(app, ["plan", "--target", str(tmp_path)])
    assert r.exit_code == 0, r.stdout
    assert "svc-a" in r.stdout and "1 service" in r.stdout


def test_cli_plan_enforces_cap(tmp_path):
    _manifest(tmp_path / "a", "a")
    _manifest(tmp_path / "b", "b")
    r = runner.invoke(app, ["plan", "--target", str(tmp_path), "--max-services", "1"])
    assert r.exit_code == 2  # over the fan-out cap
