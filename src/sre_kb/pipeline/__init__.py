"""Staged, resumable pipeline: clone(local) -> scan -> [Copilot enrich] -> validate."""

from sre_kb.pipeline.orchestrator import RunResult, run

__all__ = ["RunResult", "run"]
