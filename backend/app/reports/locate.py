"""Matches uploaded files to the inputs a report expects."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

from . import ReportType, SourceFile


@dataclass(frozen=True)
class SourceSet:
    """The stored file for each input one build reads."""
    report: ReportType
    found: dict[str, Path] = field(default_factory=dict)

    def optional(self, key: str) -> Path | None:
        """The file for input `key`, or None if it was not uploaded."""
        return self.found.get(key)


def matches(spec: SourceFile, path: Path) -> bool:
    """Whether a file's name and type say it is `spec`."""
    name = path.name.lower()
    return (path.suffix.lower() in spec.exts
            and all(f.lower() in name for f in spec.fragments)
            and not any(x.lower() in name for x in spec.excludes))
