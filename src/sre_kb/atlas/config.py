"""Explicit repository boundary and overlay configuration for atlas generation."""

from __future__ import annotations

import fnmatch
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DEFAULT_EXCLUDES = [
    ".git/**",
    ".work/**",
    ".venv/**",
    "venv/**",
    "node_modules/**",
    "target/**",
    "build/**",
    "dist/**",
    "**/__pycache__/**",
    "**/.pytest_cache/**",
    "**/.ruff_cache/**",
]
_CONFIG_API_VERSION = "sre.kb/atlas-config/v1alpha1"
_MAX_CONFIG_BYTES = 1_000_000


class AtlasConfigError(ValueError):
    """The atlas boundary or one of its declared local inputs is invalid."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectConfig(_Strict):
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    roots: list[str] = Field(min_length=1)
    testRoots: list[str] = Field(default_factory=list)
    manifests: list[str] = Field(default_factory=list)

    @field_validator("roots", "testRoots", "manifests")
    @classmethod
    def relative_paths_only(cls, values: list[str]) -> list[str]:
        for value in values:
            _validate_relative(value)
        return values


class OverlayConfig(_Strict):
    runtimeEvidence: list[str] = Field(default_factory=list)
    sbom: list[str] = Field(default_factory=list)
    coverage: list[str] = Field(default_factory=list)
    codeowners: list[str] = Field(default_factory=list)
    changeHistory: bool = False
    maxHistoryCommits: int = Field(default=200, ge=1, le=10_000)

    @field_validator("runtimeEvidence", "sbom", "coverage", "codeowners")
    @classmethod
    def local_inputs_only(cls, values: list[str]) -> list[str]:
        for value in values:
            _validate_relative(value)
        return values


class OutputConfig(_Strict):
    path: str = "docs/codebase-atlas/generated"
    maxDiagramNodes: int = Field(default=80, ge=5, le=500)
    html: bool = True

    @field_validator("path")
    @classmethod
    def relative_output_only(cls, value: str) -> str:
        _validate_relative(value)
        return value


class AtlasConfig(_Strict):
    apiVersion: Literal["sre.kb/atlas-config/v1alpha1"] = _CONFIG_API_VERSION
    projects: list[ProjectConfig] = Field(min_length=1)
    exclude: list[str] = Field(default_factory=lambda: list(DEFAULT_EXCLUDES))
    overlays: OverlayConfig = Field(default_factory=OverlayConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)

    @model_validator(mode="after")
    def unique_projects(self) -> AtlasConfig:
        names = [project.name for project in self.projects]
        if len(names) != len(set(names)):
            raise ValueError("project names must be unique")
        roots = [
            (project.name, kind, PurePosixPath(value.replace("\\", "/")))
            for project in self.projects
            for kind, values in (("source", project.roots), ("test", project.testRoots))
            for value in values
        ]
        for index, (project, kind, path) in enumerate(roots):
            for other_project, other_kind, other_path in roots[index + 1 :]:
                if path == other_path or path in other_path.parents or other_path in path.parents:
                    raise ValueError(
                        "atlas source/test roots may not overlap: "
                        f"{project}:{kind}:{path} and "
                        f"{other_project}:{other_kind}:{other_path}"
                    )
        return self


def _validate_relative(value: str) -> None:
    path = PurePosixPath(value.replace("\\", "/"))
    windows_path = PureWindowsPath(value)
    if (
        not value
        or path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or ".." in path.parts
    ):
        raise ValueError(f"atlas paths must be non-empty, relative, and contained: {value!r}")


def resolve_local_path(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    """Resolve a configured path and prove it remains under the target root."""
    target_root = root.resolve()
    raw = target_root / relative
    reject_symlink_components(target_root, raw)
    candidate = raw.resolve()
    if not candidate.is_relative_to(target_root):
        raise AtlasConfigError(f"configured path escapes target root: {relative}")
    if must_exist and not candidate.exists():
        raise AtlasConfigError(f"configured path does not exist: {relative}")
    return candidate


def reject_symlink_components(root: Path, candidate: Path) -> None:
    """Reject symlink/junction traversal anywhere below a resolved repository root."""
    target_root = root.resolve()
    try:
        relative = candidate.absolute().relative_to(target_root)
    except ValueError as exc:
        raise AtlasConfigError(f"atlas path escapes target root: {candidate}") from exc
    current = target_root
    for part in relative.parts:
        current /= part
        is_junction = getattr(current, "is_junction", lambda: False)()
        if current.is_symlink() or is_junction:
            raise AtlasConfigError(f"atlas paths may not traverse symlinks or junctions: {candidate}")


def load_config(
    root: Path,
    config_path: Path | None = None,
) -> tuple[AtlasConfig, Path, str]:
    target_root = root.resolve()
    requested = config_path or Path(".sre/atlas.yaml")
    if requested.is_absolute():
        resolved = requested.resolve()
        if not resolved.is_relative_to(target_root):
            raise AtlasConfigError("atlas config must be inside the target repository")
        reject_symlink_components(target_root, requested)
    else:
        resolved = resolve_local_path(target_root, requested.as_posix())
    if not resolved.is_file():
        rel = resolved.relative_to(target_root).as_posix()
        raise AtlasConfigError(
            f"no atlas boundary config at {rel}; create .sre/atlas.yaml before scanning"
        )
    if resolved.stat().st_size > _MAX_CONFIG_BYTES:
        raise AtlasConfigError(f"atlas config exceeds 1 MB resource limit: {resolved}")
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
        config = AtlasConfig.model_validate(raw)
    except (OSError, RecursionError, yaml.YAMLError, ValueError) as exc:
        raise AtlasConfigError(f"invalid atlas config {resolved}: {exc}") from exc
    if config.apiVersion != _CONFIG_API_VERSION:
        raise AtlasConfigError(
            f"unsupported atlas config apiVersion {config.apiVersion!r}; want {_CONFIG_API_VERSION}"
        )
    canonical = json.dumps(config.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    digest = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return config, resolved, digest


def is_excluded(relative: str, patterns: list[str]) -> bool:
    rel = relative.replace("\\", "/").lstrip("./")
    pure = PurePosixPath(rel)
    for raw in patterns:
        pattern = raw.replace("\\", "/").lstrip("./")
        if pattern.endswith("/**") and (rel == pattern[:-3] or rel.startswith(pattern[:-2])):
            return True
        if fnmatch.fnmatchcase(rel, pattern) or pure.match(pattern):
            return True
    return False
