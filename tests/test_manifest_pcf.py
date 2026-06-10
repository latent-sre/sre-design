"""PCF manifest collector: processes/sidecars/v3 services, route flags, and per-environment
`((var))` interpolation from sibling vars files."""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.collectors.common import manifest_pcf


def _apps(tmp_path):
    ctx = ScanContext(root=tmp_path, repo="file://x")
    facts = manifest_pcf.collect(ctx)
    return [f for f in facts if f.type == "pcf.app"], facts


def test_processes_and_sidecars_are_collected(tmp_path):
    """A worker-bearing app used to misreport as a single web process: the `processes:` block
    (and `sidecars:`) now lands on the fact instead of being dropped."""
    (tmp_path / "manifest.yml").write_text(
        "applications:\n"
        "- name: orders\n"
        "  instances: 2\n"
        "  processes:\n"
        "  - type: web\n"
        "    instances: 2\n"
        "    memory: 1G\n"
        "  - type: worker\n"
        "    instances: 4\n"
        "    command: bundle exec work\n"
        "  sidecars:\n"
        "  - name: envoy\n"
        "    command: ./envoy\n"
        "    process_types: [web]\n",
        encoding="utf-8")
    apps, _ = _apps(tmp_path)
    procs = {p["type"]: p for p in apps[0].attrs["processes"]}
    assert set(procs) == {"web", "worker"}
    assert procs["worker"]["instances"] == 4 and procs["worker"]["command"] == "bundle exec work"
    assert apps[0].attrs["sidecars"] == [
        {"name": "envoy", "command": "./envoy", "processTypes": ["web"]}]


def test_v3_service_maps_bind_with_parameters(tmp_path):
    (tmp_path / "manifest.yml").write_text(
        "applications:\n"
        "- name: orders\n"
        "  services:\n"
        "  - orders-postgres\n"
        "  - name: order-kafka\n"
        "    parameters: {retention: 7d}\n"
        "  - 42\n",  # junk entry: ignored, never crashes the scan
        encoding="utf-8")
    apps, facts = _apps(tmp_path)
    assert apps[0].attrs["services"] == ["orders-postgres", "order-kafka"]
    bindings = {f.attrs["name"]: f.attrs for f in facts if f.type == "pcf.service-binding"}
    assert "parameters" not in bindings["orders-postgres"]
    assert bindings["order-kafka"]["parameters"] == {"retention": "7d"}


def test_route_flags_are_collected(tmp_path):
    (tmp_path / "manifest.yml").write_text(
        "applications:\n- name: worker\n  no-route: true\n  random-route: true\n",
        encoding="utf-8")
    apps, _ = _apps(tmp_path)
    assert apps[0].attrs["noRoute"] is True and apps[0].attrs["randomRoute"] is True


def test_vars_file_interpolation_preserves_native_types(tmp_path):
    (tmp_path / "manifest.yml").write_text(
        "applications:\n"
        "- name: ((app-name))\n"
        "  instances: ((web-instances))\n"
        "  routes:\n"
        "  - route: ((app-name)).apps.internal\n"
        "  memory: ((missing))\n",
        encoding="utf-8")
    (tmp_path / "vars.yml").write_text("app-name: orders\nweb-instances: 3\n", encoding="utf-8")
    apps, _ = _apps(tmp_path)
    a = apps[0].attrs
    assert a["name"] == "orders"
    assert a["instances"] == 3                      # whole-placeholder keeps the int
    assert a["routes"] == ["orders.apps.internal"]  # in-string substitution
    assert a["memory"] == "((missing))"             # unresolved stays visible, never crashes


def test_env_variant_uses_its_own_vars_and_carries_environment(tmp_path):
    (tmp_path / "manifest.yml").write_text(
        "applications:\n- name: orders\n  instances: 1\n", encoding="utf-8")
    (tmp_path / "manifest-prod.yml").write_text(
        "applications:\n- name: orders\n  instances: ((scale))\n", encoding="utf-8")
    (tmp_path / "vars-prod.yml").write_text("scale: 6\n", encoding="utf-8")
    apps, _ = _apps(tmp_path)
    # Base manifest first — fs.first("pcf.app") keeps reading the unsuffixed manifest even
    # though 'manifest-prod.yml' sorts before 'manifest.yml' lexically.
    assert "environment" not in apps[0].attrs and apps[0].attrs["instances"] == 1
    assert apps[1].attrs["environment"] == "prod" and apps[1].attrs["instances"] == 6


def test_per_app_manifests_are_not_misread_as_environments(tmp_path):
    """manifest-api.yml + manifest-worker.yml with NO base manifest.yml is the per-app
    convention — neither file is an environment variant named 'api'/'worker'."""
    (tmp_path / "manifest-api.yml").write_text(
        "applications:\n- name: api\n", encoding="utf-8")
    (tmp_path / "manifest-worker.yml").write_text(
        "applications:\n- name: worker\n", encoding="utf-8")
    apps, _ = _apps(tmp_path)
    assert {a.attrs["name"] for a in apps} == {"api", "worker"}
    assert all("environment" not in a.attrs for a in apps)


def test_env_suffix_still_applies_beside_a_base_manifest(tmp_path):
    (tmp_path / "manifest.yml").write_text(
        "applications:\n- name: orders\n", encoding="utf-8")
    (tmp_path / "manifest-prod.yml").write_text(
        "applications:\n- name: orders\n", encoding="utf-8")
    apps, _ = _apps(tmp_path)
    envs = {a.attrs.get("environment") for a in apps}
    assert envs == {None, "prod"}
