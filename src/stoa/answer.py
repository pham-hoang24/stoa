"""Shared contract between lanes, router, eval and viewer."""
from __future__ import annotations
from dataclasses import dataclass, field

# Why an Answer has no value. The router acts on this, never on note text.
ABSTAIN_DEFER = "defer"        # lane hands the question to the llm lane
ABSTAIN_DECLINED = "declined"  # lane cannot answer reliably; do not guess


@dataclass
class Evidence:
    file: str
    label: str = ""
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None  # x0,y0,x1,y1; PDF/SVG: top-left origin, 72-point render coordinates, page=0
    global_id: str | None = None  # IFC GlobalId


@dataclass
class Answer:
    value: float | int | str | None  # None = abstain
    unit: str | None = None
    evidence: list[Evidence] = field(default_factory=list)
    lane: str = ""
    note: str = ""
    abstain: str | None = None  # ABSTAIN_* when value is None, else None
