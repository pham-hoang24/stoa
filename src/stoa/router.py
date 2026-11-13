"""Route a question to the lane that can answer it best (by source/format, not question type)."""
from __future__ import annotations

from .answer import Answer
from .data import Question


def lane_for(q: Question) -> str:
    src, ext = q.source, q.path.rsplit(".", 1)[-1].lower()
    if src in ("ifc_models", "ifc_bench") or ext == "ifc":
        return "ifc"
    if src == "swiss_dwellings":
        return "swiss"
    if ext in ("png", "jpg", "jpeg") or src == "cubicasa5k":
        return "vision"
    return "doc"  # PDFs/DXF with text: schedules and free-form


def answer(q: Question) -> Answer:
    lane = lane_for(q)
    path = q.abspath
    try:
        if lane == "ifc":
            from .lanes import ifc
            a = ifc.answer(q, path)
            if a.value is None and (q.type == "text" or "ifc_bench" in q.path or "not found" in a.note or "not recognised" in a.note):
                from .lanes import llm
                return llm.answer(q, path)
            return a
        if lane == "swiss":
            from .lanes import swiss
            return swiss.answer(q, path)
        if lane == "vision":
            from .lanes import llm
            return llm.answer(q, path)
        from .lanes import llm
        return llm.answer(q, path)
    except Exception as e:  # a lane crash must never kill a batch run
        return Answer(None, lane=lane, note=f"error: {type(e).__name__}: {e}")
