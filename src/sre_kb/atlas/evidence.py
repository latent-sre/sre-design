"""Contained file access and byte-grounded atlas evidence."""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path

from sre_kb.atlas.config import AtlasConfigError, reject_symlink_components
from sre_kb.atlas.model import AtlasEvidence, AtlasLines, EvidenceClass
from sre_kb.collectors.base import hash_excerpt

MAX_ATLAS_FILE_BYTES = 2_000_000


class EvidenceStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._lines: dict[str, list[str]] = {}
        self.scanned_paths: set[str] = set()

    def relative(self, path: Path) -> str:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise AtlasConfigError(f"atlas input escapes target root: {path}")
        return resolved.relative_to(self.root).as_posix()

    def lines(self, relative: str) -> list[str]:
        if relative not in self._lines:
            raw = self.root / relative
            reject_symlink_components(self.root, raw)
            path = raw.resolve()
            if not path.is_relative_to(self.root):
                raise AtlasConfigError(f"atlas input escapes target root: {relative}")
            if not path.is_file():
                raise AtlasConfigError(f"atlas input is not a regular file: {relative}")
            if path.stat().st_size > MAX_ATLAS_FILE_BYTES:
                raise AtlasConfigError(f"atlas input exceeds 2 MB resource limit: {relative}")
            self._lines[relative] = path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines(keepends=True)
            self.scanned_paths.add(relative)
        return self._lines[relative]

    def text(self, relative: str) -> str:
        return "".join(self.lines(relative))

    def evidence(
        self,
        relative: str,
        start: int,
        end: int,
        detector: str,
        evidence_class: EvidenceClass,
    ) -> AtlasEvidence:
        lines = self.lines(relative)
        if not lines:
            lines = ["\n"]
            self._lines[relative] = lines
        start = max(1, min(start, len(lines)))
        end = max(start, min(end, len(lines)))
        return AtlasEvidence(
            evidenceClass=evidence_class,
            detector=detector,
            path=relative,
            lines=AtlasLines(start=start, end=end),
            excerptHash=hash_excerpt(lines, start, end),
        )

    def find_line(self, relative: str, needle: str, *, default: int = 1) -> int:
        for index, line in enumerate(self.lines(relative), start=1):
            if needle in line:
                return index
        return default

    def tree_digest(self) -> str:
        digest = hashlib.sha256()
        for relative in sorted(self.scanned_paths):
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(self.text(relative).encode("utf-8"))
            digest.update(b"\0")
        return "sha256:" + digest.hexdigest()


def safe_xml_root(text: str) -> ET.Element:
    """Parse bounded local XML after rejecting DTD/entity expansion constructs."""
    upper = text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise ValueError("DTD and entity declarations are not accepted in atlas XML inputs")
    return ET.fromstring(text)  # noqa: S314 - declarations rejected; input is bounded to 2 MB
