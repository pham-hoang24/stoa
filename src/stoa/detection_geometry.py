"""Image views and source-coordinate detection geometry, with no reference data."""
from __future__ import annotations

import math
from dataclasses import dataclass

import cv2

from .assets import Drawing


@dataclass(frozen=True)
class View:
    id: str
    rect: tuple[int, int, int, int]
    png: bytes
    overview: bool = False


@dataclass(frozen=True)
class Detection:
    box: tuple[float, float, float, float]
    view: str
    edge: bool = False
    uncertain: bool = False


def _starts(length, edge, overlap):
    if length <= edge:
        return [0]
    values = list(range(0, length - edge + 1, edge - overlap))
    if values[-1] != length - edge:
        values.append(length - edge)
    return values


def views(drawing: Drawing, tile_edge=1400, overlap=200, max_requests=9) -> tuple[View, ...]:
    if tile_edge < 64 or not 0 <= overlap < tile_edge or not 1 <= max_requests <= 100:
        raise ValueError("Invalid crop or request-budget settings")
    xs, ys = _starts(drawing.width, tile_edge, overlap), _starts(drawing.height, tile_edge, overlap)
    detailed = drawing.width > tile_edge or drawing.height > tile_edge
    needed = 1 + len(xs) * len(ys) if detailed else 1
    if needed > max_requests:
        raise ValueError(f"Complete image coverage needs {needed} requests at this detail level; budget is {max_requests}. Increase the budget or upload a smaller scoped drawing")
    pixels = drawing.pixels()
    ratio = min(1, tile_edge / max(drawing.width, drawing.height))
    overview = cv2.resize(pixels, (max(1, round(drawing.width * ratio)), max(1, round(drawing.height * ratio)))) if ratio < 1 else pixels
    ok, png = cv2.imencode(".png", overview)
    if not ok:
        raise ValueError("Image encoding failed")
    result = [View("overview", (0, 0, drawing.width, drawing.height), png.tobytes(), True)]
    if detailed:
        for y in ys:
            for x in xs:
                x1, y1 = min(x + tile_edge, drawing.width), min(y + tile_edge, drawing.height)
                ok, png = cv2.imencode(".png", pixels[y:y1, x:x1])
                if not ok:
                    raise ValueError("Crop encoding failed")
                result.append(View(f"crop-{len(result)}", (x, y, x1, y1), png.tobytes()))
    return tuple(result)


def project(box, view: View, uncertain=False) -> Detection:
    if (not isinstance(box, (tuple, list)) or len(box) != 4
            or not all(isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v) for v in box)):
        raise ValueError("Every detection needs four finite coordinates")
    x0, y0, x1, y1 = box
    if not (0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 1000):
        raise ValueError("Detection coordinates must be ordered and inside the image")
    left, top, right, bottom = view.rect
    source = (left + x0 * (right - left) / 1000, top + y0 * (bottom - top) / 1000,
              left + x1 * (right - left) / 1000, top + y1 * (bottom - top) / 1000)
    if source[2] - source[0] < 1 or source[3] - source[1] < 1:
        raise ValueError("A detection is smaller than a source pixel; request a more legible image")
    return Detection(source, view.id, min(x0, y0) <= 2 or max(x1, y1) >= 998, uncertain)


def overlap(a, b) -> tuple[float, float]:
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    area_a, area_b = (a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])
    return intersection / (area_a + area_b - intersection), intersection / min(area_a, area_b)


def deduplicate(detections: list[Detection]) -> tuple[tuple[Detection, ...], bool]:
    kept = []
    ambiguous = False
    # Larger boxes first so a crop-edge fragment can join its full detection.
    for item in sorted(detections, key=lambda d: (-(d.box[2] - d.box[0]) * (d.box[3] - d.box[1]), d.box, d.view)):
        duplicate = False
        for existing in kept:
            iou, containment = overlap(item.box, existing.box)
            if item.view != existing.view and (iou >= 0.7 or (item.edge and containment >= 0.85)):
                duplicate = True
                break
            if iou > 0.3:
                ambiguous = True
        if not duplicate:
            kept.append(item)
    return tuple(sorted(kept, key=lambda d: (d.box[1], d.box[0], d.box[3], d.box[2]))), ambiguous
