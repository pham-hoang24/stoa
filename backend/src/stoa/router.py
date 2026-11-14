"""Route a question to the lane that can answer it best (by source/format, not question type)."""
from __future__ import annotations

import importlib

from .answer import ABSTAIN_DEFER, Answer
from .data import Question

# lane name -> module under stoa.lanes (imported lazily: ifcopenshell/ezdxf are heavy)
LANE_MODULES = {"ifc": "ifc", "swiss": "swiss", "vision": "vision", "schedules": "schedules", "doc": "llm"}


def lane_for(q: Question) -> str:
    src, ext = q.source, q.path.rsplit(".", 1)[-1].lower()
    if src in ("ifc_models", "ifc_bench") or ext == "ifc":
        return "ifc"
    if src == "swiss_dwellings":
        return "swiss"
    if src == "opening_design":
        return "schedules"
    if ext in ("png", "jpg", "jpeg") or src == "cubicasa5k":
        return "vision"
    return "doc"  # PDFs/DXF with text: schedules and free-form


def _lane_module(lane: str):
    return importlib.import_module(f".lanes.{LANE_MODULES[lane]}", __package__)


def answer(q: Question) -> Answer:
    lane = lane_for(q)
    try:
        a = _lane_module(lane).answer(q, q.abspath)
        if a.value is None and a.abstain == ABSTAIN_DEFER:
            return _lane_module("doc").answer(q, q.abspath)
        return a
    except Exception as e:  # a lane crash must never kill a batch run
        return Answer(None, lane=lane, note=f"error: {type(e).__name__}: {e}")
