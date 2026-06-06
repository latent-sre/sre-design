"""SCM-neutral Forge seam. GitHub uses git + the REST API (token from env); the local
forge backs --dry-run."""

from sre_kb.publish.forge.base import Forge, ForgePublishError
from sre_kb.publish.forge.github import GitHubForge
from sre_kb.publish.forge.local import LocalForge


def get_forge(name: str, *, allowed_repos: list[str] | None = None) -> Forge:
    cls = {"github": GitHubForge, "local": LocalForge}.get(name, LocalForge)
    return cls(allowed_repos=allowed_repos) if cls is GitHubForge else cls()


__all__ = ["Forge", "ForgePublishError", "GitHubForge", "LocalForge", "get_forge"]
