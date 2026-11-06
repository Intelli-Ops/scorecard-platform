"""Notes a build records about itself: warnings and checks."""
from __future__ import annotations
from dataclasses import dataclass, field

INFO, WARNING, ACTION = "info", "warning", "action"

SEVERITY_ORDER = {ACTION: 0, WARNING: 1, INFO: 2}


@dataclass(frozen=True)
class Note:
    code: str                       # stable slug - compare across weeks
    severity: str
    message: str                    # the .bat pipeline's wording, unchanged
    detail: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


def info(code: str, message: str, **detail) -> Note:
    return Note(code, INFO, message, detail)


def warning(code: str, message: str, **detail) -> Note:
    return Note(code, WARNING, message, detail)


def action(code: str, message: str, **detail) -> Note:
    return Note(code, ACTION, message, detail)


def sort_notes(notes: list[Note]) -> list[Note]:
    """Most serious first."""
    return sorted(notes, key=lambda n: SEVERITY_ORDER.get(n.severity, 9))
