"""Matches uploaded files to the inputs a report expects."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

from . import ReportType, SourceFile


@dataclass(frozen=True)
class SourceSet:
    """The files found for one report, and the ones that are missing."""
    report: ReportType
    found: dict[str, Path] = field(default_factory=dict)
    missing: tuple[SourceFile, ...] = ()
    ambiguous: dict[str, tuple[Path, ...]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True when every required file is present."""
        return not any(s.required for s in self.missing)

    def path(self, key: str) -> Path:
        if key not in self.found:
            spec = next((s for s in self.report.sources if s.key == key), None)
            frags = ", ".join(spec.fragments) if spec else key
            raise FileNotFoundError(
                f"No uploaded file for {self.report.label} whose name contains: {frags}")
        return self.found[key]

    def optional(self, key: str) -> Path | None:
        return self.found.get(key)

    def problems(self) -> list[str]:
        """Plain sentences for the upload screen."""
        out = [f"Missing: {s.label} - no uploaded file whose name contains "
               f"{', '.join(repr(f) for f in s.fragments)}"
               for s in self.missing if s.required]
        out += [f"Optional file not supplied: {s.label}"
                for s in self.missing if not s.required]
        out += [f"More than one file matches {key}: "
                + ", ".join(p.name for p in paths)
                for key, paths in self.ambiguous.items()]
        return out


def matches(spec: SourceFile, path: Path) -> bool:
    name = path.name.lower()
    return (path.suffix.lower() in spec.exts
            and all(f.lower() in name for f in spec.fragments)
            and not any(x.lower() in name for x in spec.excludes))
