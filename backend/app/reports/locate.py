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
            and all(f.lower() in name for f in spec.fragments))


def locate(report: ReportType, paths: list[Path]) -> SourceSet:
    """Work out which uploaded file is which. Never reads file contents."""
    found: dict[str, Path] = {}
    missing: list[SourceFile] = []
    ambiguous: dict[str, tuple[Path, ...]] = {}

    for spec in report.sources:
        hits = sorted((p for p in paths if _matches(spec, p)), key=lambda p: p.name)
        if not hits:
            missing.append(spec)
        else:
            # First match wins, as the .bat pipeline did. A second match is
            # reported rather than silently ignored: two Payment Detail files in
            # one week means someone uploaded the wrong month, and picking one
            # quietly is how a whole report goes out wrong.
            found[spec.key] = hits[0]
            if len(hits) > 1:
                ambiguous[spec.key] = tuple(hits)

    return SourceSet(report=report, found=found,
                     missing=tuple(missing), ambiguous=ambiguous)


def locate_dir(report: ReportType, directory: Path) -> SourceSet:
    """Locate against a folder on disk - used by the golden-master test, which
    runs against the same inputs/<week>/ folders the .bat pipeline uses."""
    return locate_dirs(report, [directory])


def locate_dirs(report: ReportType, directories: list[Path]) -> SourceSet:
    """Locate across several folders, EARLIER FOLDERS WINNING.

    The All-Providers .bat pipeline reads from its own week folder and the GFS
    one, in that order, because the seven shared files live with GFS while its
    own Case ARs live with it. Order is the whole mechanism: both folders hold a
    file called "Combined Custom Case AR.xlsb", and they are different files -
    Tuesday's and Thursday's.

    Merging the folders into one list and matching over that loses the
    preference, and picks whichever name happens to sort first. It did: the
    golden-master fixture silently read Tuesday's 239.7 MB copy for an
    All-Providers run and produced 467,233 rows instead of 468,267.

    The platform itself does not rely on this - uploads carry their report - but
    anything reading the legacy folders must honour the order.
    """
    for d in directories:
        if not Path(d).exists():
            raise FileNotFoundError(f"{d} does not exist")

    found: dict[str, Path] = {}
    missing: list[SourceFile] = []
    ambiguous: dict[str, tuple[Path, ...]] = {}

    for spec in report.sources:
        for d in directories:
            hits = sorted((p for p in Path(d).iterdir()
                           if p.is_file() and _matches(spec, p)),
                          key=lambda p: p.name)
            if hits:
                found[spec.key] = hits[0]
                if len(hits) > 1:
                    ambiguous[spec.key] = tuple(hits)
                break
        else:
            missing.append(spec)

    return SourceSet(report=report, found=found,
                     missing=tuple(missing), ambiguous=ambiguous)
