"""Configuration loading: packaged defaults + optional file overlay + env overrides.

Resolves repo paths (schemas, registry, prompts) relative to the package root so the
CLI works regardless of the current working directory.
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
    return repo_root() / "schemas"


def registry_path() -> Path:
    return repo_root() / "schemas" / "registry.yaml"
