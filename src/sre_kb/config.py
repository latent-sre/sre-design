"""Configuration loading: packaged defaults + optional file overlay + env overrides.

Schemas and the default config ship as package data, so they resolve relative to the installed
package and work in a wheel install, not just an editable checkout.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml


def _package_dir() -> Path:
    """Directory of the installed `sre_kb` package — the root for bundled data (schemas, config)."""
    return Path(__file__).resolve().parent


@cache
def load_config() -> dict:
    """Load the bundled data/default.yaml. (Profile + env overlay land in a later phase.)"""
    cfg_path = _package_dir() / "data" / "default.yaml"
    with cfg_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def schemas_dir() -> Path:
    """Bundled JSON Schemas, shipped as package data so they resolve in a wheel install too."""
    return _package_dir() / "schemas"


def registry_path() -> Path:
    return schemas_dir() / "registry.yaml"
