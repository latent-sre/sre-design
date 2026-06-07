"""Configuration loading: packaged defaults + optional file overlay + env overrides.

Schemas/registry ship as package data, so they resolve relative to the installed package and
work in a wheel install (not just an editable checkout). config/default.yaml is still resolved
from the repo root (dev/editable); packaging it is a follow-up.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml


@cache
def repo_root() -> Path:
    """Return the sre-design repo root (two levels up from this file: src/sre_kb/..)."""
    return Path(__file__).resolve().parents[2]


@cache
def load_config() -> dict:
    """Load config/default.yaml. (Profile + env overlay land in a later phase.)"""
    cfg_path = repo_root() / "config" / "default.yaml"
    with cfg_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def schemas_dir() -> Path:
    """Bundled JSON Schemas, shipped as package data so they resolve in a wheel install too."""
    return Path(__file__).resolve().parent / "schemas"


def registry_path() -> Path:
    return schemas_dir() / "registry.yaml"
