"""Backstage catalog-info.yaml projection (KB as a service catalog component)."""

from __future__ import annotations


def catalog_info(service: str, docs: list[dict]) -> dict:
    entry = next((d for d in docs if d.get("kind") == "ServiceCatalogEntry"), None)
    spec = entry.get("spec", {}) if entry else {}
    depends_on = [f"resource:{d}" for d in spec.get("dependsOn", [])]
    provides = [f"api:{service}{p}" for p in spec.get("providesApis", [])]
    return {
        "apiVersion": "backstage.io/v1alpha1",
        "kind": "Component",
        "metadata": {
            "name": service,
            "annotations": {"sre.kb/generated": "true"},
            "tags": ["sre-kb"],
        },
        "spec": {
            "type": spec.get("type", "service"),
            "lifecycle": spec.get("lifecycle", "production"),
            "owner": spec.get("owner", "unknown"),
            "providesApis": provides,
            "dependsOn": depends_on,
        },
    }
