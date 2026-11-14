"""Explicit user corrections; original machine proposals are never overwritten."""
from __future__ import annotations

import math

from .image_runtime import Assessment


def validate_boxes(boxes, width, height):
    if not isinstance(boxes, list) or len(boxes) > 2000:
        raise ValueError("Provide at most 2,000 source-pixel boxes")
    kept = []
    for box in boxes:
        if (not isinstance(box, (list, tuple)) or len(box) != 4
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in box)):
            raise ValueError("Every box needs four finite source-pixel coordinates")
        x0, y0, x1, y1 = map(float, box)
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            raise ValueError("A box is outside the drawing or has reversed coordinates")
        candidate = (x0, y0, x1, y1)
        if candidate in kept:
            raise ValueError("Duplicate review boxes must be removed")
        kept.append(candidate)
    return tuple(kept)


def review(assessment: Assessment, boxes, reviewer: str, confirmed_complete: bool) -> dict:
    if assessment.task is None:
        raise ValueError("Clarify a supported count task before reviewing objects")
    if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 100:
        raise ValueError("Identify who reviewed the drawing")
    if confirmed_complete is not True:
        raise ValueError("Confirm that the full image was reviewed before saving a count")
    corrected = validate_boxes(boxes, assessment.drawing.width, assessment.drawing.height)
    return {"drawing": assessment.drawing.metadata(), "task": {"target": assessment.task.target, "scope": assessment.task.scope},
            "machine": assessment.payload(),
            "review": {"status": "user_reviewed", "reviewer": reviewer.strip(), "confirmed_complete": True,
                       "count": len(corrected), "boxes": corrected,
                       "label_origin": "model_assisted_correction"}}
