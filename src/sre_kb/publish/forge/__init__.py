"""SCM-neutral Forge seam. GitHub uses git + the REST API (deferred to a later phase);
the local forge backs --dry-run."""

from sre_kb.publish.forge.base import Forge
from sre_kb.publish.forge.github import GitHubForge
from sre_kb.publish.forge.local import LocalForge


def get_forge(name: str) -> Forge:
    return {"github": GitHubForge, "local": LocalForge}.get(name, LocalForge)()


__all__ = ["Forge", "GitHubForge", "LocalForge", "get_forge"]
