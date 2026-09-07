"""What a run has to say about itself, as data.

The .bat pipeline printed these under "STEP 4 THINGS WORTH YOUR EYES" and they
were gone when the window closed. They are the most valuable output of a run
after the numbers themselves - they are the reason a person looks at the
report before it goes out.

A sentence cannot be sorted, counted, filtered or compared against last week.
A Note can. The wording is kept identical to the .bat pipeline so nothing a
reader already recognises changes meaning; the code, severity and detail are
added around it.
"""
from __future__ import annotations
from dataclasses import dataclass, field

# INFO      context. Nothing is wrong; useful to see.
# WARNING   something was dropped, corrected or duplicated. Usually expected,
#           but the count is worth a glance - a jump week on week is a signal.
# ACTION    a figure the report shows is missing or not counted. Someone has to
#           decide whether to send it anyway.
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

    def as_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity,
                "message": self.message, "detail": self.detail}


def info(code: str, message: str, **detail) -> Note:
    return Note(code, INFO, message, detail)


def warning(code: str, message: str, **detail) -> Note:
    return Note(code, WARNING, message, detail)


def action(code: str, message: str, **detail) -> Note:
    return Note(code, ACTION, message, detail)


def sort_notes(notes: list[Note]) -> list[Note]:
    """Most serious first. Stable, so same-severity notes keep run order."""
    return sorted(notes, key=lambda n: SEVERITY_ORDER.get(n.severity, 9))
