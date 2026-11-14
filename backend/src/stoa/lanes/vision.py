"""CubiCasa raster lane: count doors and windows from VLM detections; abstain on everything else.

The VLM is asked for one box per object (0..1000 image-relative, its native grid); code converts to source pixels, validates the boxes, drops duplicates and counts them, so
every answer is backed by numbered `Evidence` boxes in source-image pixels (page=0, origin top-left).
Zero valid objects is a real answer (0); a reply that cannot be parsed is an abstention, never a 0.
No dataset priors: templates this lane cannot detect decline explicitly.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..answer import ABSTAIN_DECLINED, Answer, Evidence
from ..data import Question
from . import llm

# Templates answered from detections: key -> (regex over casefolded question, singular noun for labels/prompt)
DETECTABLE = {
    "doors": (r"\bdoors\b|\bovea\b|\boven\b", "door"),
    "windows": (r"windows|ikkun", "window"),
}
# Templates in the dataset we know about but cannot count from boxes (decline, do not guess).
UNSUPPORTED = {
    "bathrooms": r"bathrooms or washrooms|kylpy- tai pesuhuone",
    "wc_rooms": r"separate wc rooms|erillistä wc-tila",
    "wc_seats": r"toilet bowls|wc-istuin",
    "showers_tubs": r"showers and bathtubs|suihkua ja kylpyammet",
    "sinks": r"sinks and wash basins|pesu- ja tiskiallas",
    "floors": r"floors \(storeys\)|kerrosta",
    "bedrooms": r"bedrooms|makuuhuone",
    "kitchens": r"kitchens|keittiö",
    "saunas": r"saunas|saunaa",
    "balconies": r"balcon|parveke",
}

MIN_SIDE = 4          # px: smaller boxes are noise
MAX_FRACTION = 0.5    # a single door/window covering over half the image is not a door/window
DEDUPE_IOU = 0.5
MAX_DETECTIONS = 40   # more than this from one image means the reply is not a usable detection list

SCALE = 1000  # the VLM is asked for 0..1000 image-relative coordinates (its native grid); code converts to source pixels
PROMPT = (
    "Find every {noun} drawn on this floor plan. {rule}Reply with JSON only, no prose: "
    "{{\"detections\": [{{\"box\": [x0, y0, x1, y1]}}, ...]}} where each box is the tight bounding box of one {noun}, "
    "in coordinates relative to the image from 0 to 1000 (x0,y0 = top-left corner, x1,y1 = bottom-right corner; "
    "0,0 is the image's top-left, 1000,1000 its bottom-right). List each {noun} once; never repeat a box. "
    "If there is none reply {{\"detections\": []}}."
)
RULES = {
    "door": "Count door leaves (swing arcs or door symbols); an open doorway without a door leaf is not a door. ",
    "window": "",
}


def classify(question: str) -> tuple[str | None, str | None]:
    """(key, 'detect'|'unsupported') for a question, or (None, None) when it is not a known template."""
    ql = question.casefold()
    for key, (pat, _) in DETECTABLE.items():
        if re.search(pat, ql):
            return key, "detect"
    for key, pat in UNSUPPORTED.items():
        if re.search(pat, ql):
            return key, "unsupported"
    return None, None


def image_size(path: Path) -> tuple[int, int]:
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"cannot decode image {path.name}")
    h, w = img.shape[:2]
    return w, h


def parse_boxes(reply: str) -> list | None:
    """Raw box candidates from a reply, or None when the reply is not a detection list."""
    m = re.search(r"\{.*\}", reply, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    dets = data.get("detections") if isinstance(data, dict) else None
    if not isinstance(dets, list):
        return None
    return [d.get("box") if isinstance(d, dict) else d for d in dets]


def _iou(a, b) -> float:
    iw = min(a[2], b[2]) - max(a[0], b[0])
    ih = min(a[3], b[3]) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def to_pixels(box, w: int, h: int):
    """Relative 0..1000 box -> source pixels; non-box values pass through for validate() to reject."""
    if isinstance(box, (list, tuple)) and len(box) == 4 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in box):
        return [box[0] * w / SCALE, box[1] * h / SCALE, box[2] * w / SCALE, box[3] * h / SCALE]
    return box


def validate(raw: list, w: int, h: int) -> list[tuple[float, float, float, float]]:
    """Keep well-formed, in-image, plausibly sized boxes; drop near-duplicates (first one wins)."""
    kept: list[tuple[float, float, float, float]] = []
    for b in raw:
        if not (isinstance(b, (list, tuple)) and len(b) == 4 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in b)):
            continue
        x0, y0, x1, y1 = (float(v) for v in b)
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        x0, y0, x1, y1 = max(x0, 0.0), max(y0, 0.0), min(x1, float(w)), min(y1, float(h))  # clamp into the image
        if x1 - x0 < MIN_SIDE or y1 - y0 < MIN_SIDE:
            continue
        if (x1 - x0) * (y1 - y0) > MAX_FRACTION * w * h:
            continue
        box = (x0, y0, x1, y1)
        if all(_iou(box, k) <= DEDUPE_IOU for k in kept):
            kept.append(box)
    return kept


def declined(note: str) -> Answer:
    return Answer(None, "count", lane="vision", note=f"declined: {note}", abstain=ABSTAIN_DECLINED)


def answer(q: Question, path: Path) -> Answer:
    key, mode = classify(q.question)
    if mode != "detect":
        what = f"template '{key}'" if key else "question"
        return declined(f"{what} is not supported by the vision lane (no detector)")
    noun = DETECTABLE[key][1]
    ext = path.suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg"):
        return declined(f"unsupported image type {ext}")
    w, h = image_size(path)
    msg = PROMPT.format(noun=noun, rule=RULES[noun])
    content = [{"type": "text", "text": msg}, llm.image_part(path.read_bytes(), "image/png" if ext == ".png" else "image/jpeg")]
    try:
        reply = llm.chat([{"role": "system", "content": llm.SYSTEM_DRAWING}, {"role": "user", "content": content}], max_tokens=800)
    except llm.LLMError as e:
        return declined(f"provider unavailable: {e}")
    raw = parse_boxes(reply)
    if raw is None or len(raw) > MAX_DETECTIONS:
        return declined(f"detector reply could not be parsed as a {noun} list")
    boxes = validate([to_pixels(b, w, h) for b in raw], w, h)
    ev = [Evidence(str(path), f"{noun} {i}", page=0, bbox=b) for i, b in enumerate(boxes, 1)]
    note = f"{len(boxes)} {noun} box(es) kept of {len(raw)} reported"
    if not ev:  # a true zero still points at the image it was counted on
        ev = [Evidence(str(path), f"no {noun} detected", page=0)]
    return Answer(len(boxes), "count", ev, "vision", note)
