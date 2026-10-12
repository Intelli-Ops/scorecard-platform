"""Matching uploaded files to the inputs a report expects.

The .bat pipeline scanned a folder and matched filenames on the fly. Here the
files arrive as uploads, so locating them is a separate step that happens
BEFORE any reading: the upload screen can then tell someone a file is missing
while they are still sat there, rather than failing two minutes into a run.

Matching rules are unchanged from the .bat pipeline - case-insensitive, every
fragment must appear somewhere in the name. That is what lets a file keep its
trailing date ("... WC 08.31.2026.xlsb") and never be renamed by hand.
"""
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
        """True when every REQUIRED file is present. Optional ones may be absent."""
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
        """Plain sentences for the upload screen. Empty list means good to run."""
        out = [f"Missing: {s.label} - no uploaded file whose name contains "
               f"{', '.join(repr(f) for f in s.fragments)}"
               for s in self.missing if s.required]
        out += [f"Optional file not supplied: {s.label}"
                for s in self.missing if not s.required]
        out += [f"More than one file matches {key}: "
                + ", ".join(p.name for p in paths)
                for key, paths in self.ambiguous.items()]
        return out


def _matches(spec: SourceFile, path: Path) -> bool:
    name = path.name.lower()
    return (path.suffix.lower() in spec.exts
            and all(f.lower() in name for f in spec.fragments)
            and not any(x.lower() in name for x in spec.excludes))
