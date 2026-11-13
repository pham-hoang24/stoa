"""Shared contract between lanes, router, eval and viewer."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Evidence:
    file: str
    label: str = ""
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None  # x0,y0,x1,y1 in file coords
    global_id: str | None = None  # IFC GlobalId


@dataclass
class Answer:
    value: float | int | str | None  # None = abstain
    unit: str | None = None
    evidence: list[Evidence] = field(default_factory=list)
    lane: str = ""
    note: str = ""
