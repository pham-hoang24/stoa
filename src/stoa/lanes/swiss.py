"""Swiss Dwellings lane: rule-based geometry on the DXF twin of each PDF (no LLM).

Rules were fitted on the 65 preview floors against ground truth (see docs/research):
  doors      = 5-vertex DOOR polylines          windows = 4-vertex WINDOW polylines
  bathtub    = 69-vertex FIXTURE polyline        shower  = 5-vertex FIXTURE polyline
  washbasin  = 48-vertex FIXTURE polyline containing a FIXTURE circle (drain)
  WC         = other 48-vertex FIXTURE polylines
  room area  = shoelace area of the closed ROOM_OUTLINE polygon containing the room number text
  apartments = unique 'Whg. X' tags
"""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf
from ezdxf.math import Vec2, is_point_in_polygon_2d

from ..answer import ABSTAIN_DECLINED, ABSTAIN_DEFER, Answer, Evidence
from ..data import Question, sibling
from ..qparse import norm, quoted

NUM_RE = re.compile(r"^[A-Za-z]{0,2}\d+(?:\.\d+)+$|^\d+\.\d+$")
AREA_RE = re.compile(r"^\d+(?:\.\d+)?\s*m²$")
APT_RE = re.compile(r"^(?:Whg\.?|Appt\.?|App\.?|Appart\.?|Apt\.?|Wohnung|Appartamento|App\.)\s*([A-Z]{1,2})$", re.I)
# rooms not counted as indoor net area (outdoor spaces, shafts, voids), multilingual stems
EXCLUDED_STEMS = (
    "balkon", "loggia", "terrasse", "terrazza", "balcon", "balcone", "sitzplatz", "aussen", "außen", "dachterrasse",
    "veranda", "gartensitz", "pergola", "schacht", "luftraum", "gaine", "vide", "cavedio", "vuoto", "shaft",
    "void", "pozzo", "extérieur", "esterno", "aussenraum", "wintergarten", "terrasse", "patio",
)


@dataclass
class Room:
    name: str
    number: str
    poly: list[tuple[float, float]]
    area: float
    apt_tag: str | None = None
    unit: int | None = None


@dataclass
class Plan:
    path: Path
    rooms: list[Room] = field(default_factory=list)
    doors: int = 0
    windows: int = 0
    wc: int = 0
    washbasins: int = 0
    bathtubs: int = 0
    showers: int = 0
    apartments: set[str] = field(default_factory=set)
    anchors: list[tuple[str, float, float]] = field(default_factory=list)  # (room number, x, y) in DXF space


def _shoelace(p) -> float:
    return abs(sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p)))) / 2


def _inside(pt, poly) -> bool:
    return is_point_in_polygon_2d(Vec2(pt), [Vec2(p) for p in poly]) >= 0


def _ring(e):
    return [(float(x), float(y)) for x, y, *_ in e.get_points()]


@functools.lru_cache(maxsize=64)
def load(dxf_path: str) -> Plan:
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    plan = Plan(Path(dxf_path))
    polys, texts, units, circles, fx = [], [], [], [], []
    for e in msp:
        L, t = e.dxf.layer, e.dxftype()
        if t == "LWPOLYLINE":
            pts = _ring(e)
            n = len(pts)
            if L == "ROOM_OUTLINE" and e.closed and n >= 3 and _shoelace(pts) > 0.3:
                polys.append(pts)
            elif L == "UNIT_OUTLINE" and n >= 3:
                units.append(pts)
            elif L == "DOOR" and n == 5:
                plan.doors += 1
            elif L == "WINDOW" and n == 4:
                plan.windows += 1
            elif L == "FIXTURE":
                fx.append(pts)
        elif t == "TEXT" and L == "ROOM_TEXT":
            texts.append((e.dxf.text.strip(), float(e.dxf.insert[0]), float(e.dxf.insert[1])))
        elif t == "CIRCLE" and L == "FIXTURE":
            circles.append((float(e.dxf.center[0]), float(e.dxf.center[1])))
    for pts in fx:
        n = len(pts)
        if n == 69:
            plan.bathtubs += 1
        elif n == 5:
            plan.showers += 1
        elif n == 48:
            if any(_inside((cx, cy), pts) for cx, cy in circles):
                plan.washbasins += 1
            else:
                plan.wc += 1
    # texts -> smallest containing polygon
    order = sorted(range(len(polys)), key=lambda i: _shoelace(polys[i]))
    buckets: dict[int, list[tuple[str, float, float]]] = {}
    for tx in texts:
        for i in order:
            if _inside((tx[1], tx[2]), polys[i]):
                buckets.setdefault(i, []).append(tx)
                break
    for i, items in buckets.items():
        num = next((t for t, *_ in items if NUM_RE.match(t) and not AREA_RE.match(t)), None)
        if not num:
            continue
        name_parts, tag = [], None
        for t, *_ in items:
            if t == num or AREA_RE.match(t):
                continue
            m = APT_RE.match(t)
            if m:
                tag = m.group(1).upper()
            else:
                name_parts.append(t)
        room = Room(" ".join(name_parts), num, polys[i], _shoelace(polys[i]), tag)
        for ui, u in enumerate(units):
            if _inside(items[0][1:], u):
                room.unit = ui
        plan.rooms.append(room)
        nx = next((t for t in items if t[0] == num), items[0])
        plan.anchors.append((num, nx[1], nx[2]))
        if tag:
            plan.apartments.add(tag)
    return plan


def excluded(name: str) -> bool:
    n = norm(name)
    return bool(n) and any(s in n for s in EXCLUDED_STEMS)


def _bbox(poly):
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return (min(xs), min(ys), max(xs), max(ys))


def _pdf_transform(plan: Plan, pdf: Path):
    """Affine DXF->PDF-points map (uniform scale, y flip) fitted on room-number text anchors."""
    import numpy as np
    import pymupdf
    pts = []
    with pymupdf.open(pdf) as doc:
        page = doc[0]
        for num, x, y in plan.anchors:
            hits = page.search_for(num)
            if len(hits) == 1:
                r = hits[0]
                pts.append((x, y, (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
    if len(pts) < 3:
        return None
    a = np.array(pts)
    A = np.zeros((2 * len(a), 3)); b = np.zeros(2 * len(a))
    A[0::2] = np.c_[a[:, 0], np.ones(len(a)), np.zeros(len(a))]; b[0::2] = a[:, 2]
    A[1::2] = np.c_[-a[:, 1], np.zeros(len(a)), np.ones(len(a))]; b[1::2] = a[:, 3]
    s_, tx, ty = np.linalg.lstsq(A, b, rcond=None)[0]
    return lambda x, y: (s_ * x + tx, -s_ * y + ty)


def _ev(path: Path, rooms: list[Room], plan: Plan | None = None) -> list[Evidence]:
    """Evidence boxes in PDF page points when a PDF twin exists, else DXF units."""
    tf = None
    pdf = path if path.suffix == ".pdf" else sibling(path, ".pdf")
    if plan is not None and pdf is not None:
        try:
            tf = _pdf_transform(plan, pdf)
        except Exception:
            tf = None
    out = []
    for r in rooms:
        x0, y0, x1, y1 = _bbox(r.poly)
        label = f"{r.number} {r.name}"
        if tf:
            (a, b), (c, d) = tf(x0, y0), tf(x1, y1)
            poly = [(float(x), float(y)) for x, y in (tf(px, py) for px, py in r.poly)]
            out.append(Evidence(str(pdf), label, page=0, bbox=(float(min(a, c)), float(min(b, d)), float(max(a, c)), float(max(b, d))), polygon=poly))
        else:
            out.append(Evidence(str(path), label, bbox=(x0, y0, x1, y1), polygon=list(r.poly)))
    return out


def _intent(q: str) -> str:
    ql = q.casefold()
    quotes = quoted(q)
    area = bool(re.search(r"m²", ql)) and bool(re.search(r"area|fläche|surface|superficie|nettofl", ql))
    if area:
        if re.search(r"apartment [a-z]\b|wohnung [a-z]\b|appartement [a-z]\b|appartamento [a-z]\b|logement [a-z]\b", ql):
            return "apt_area"
        if re.search(r"(?:room|raum|pièce|locale) [\w.]+ ?[\(«]", ql):
            return "room_area"
        if quotes and re.search(r"total|gesamt|totale", ql):
            return "label_area"
        return "indoor_area"
    if re.search(r"apartment|wohnung|appartement|appartamenti|unità abitative|logement", ql):
        return "apartments"
    if quotes:
        return "label_count"
    for key, pat in (("doors", r"door|türen|portes|porte\b"), ("windows", r"window|fenster|fenêtre|finestre"),
                     ("wc", r"toilet|\bwcs?\b"), ("washbasins", r"washbasin|lavabo|lavabi|waschbecken|lavandini"),
                     ("bathtubs", r"bathtub|badewanne|baignoire|vasche"), ("showers", r"shower|dusche|douche|docce")):
        if re.search(pat, ql):
            return key
    return "unknown"


def answer(q: Question, path: Path) -> Answer:
    dxf = path if path.suffix == ".dxf" else sibling(path, ".dxf")
    if dxf is None:
        return Answer(None, lane="swiss", note=f"declined: no DXF twin for {path.name}", abstain=ABSTAIN_DECLINED)
    plan = load(str(dxf))
    intent = _intent(q.question)
    quotes = quoted(q.question)
    ev = [Evidence(str(path), "floor plan")]
    if intent in ("doors", "windows", "wc", "washbasins", "bathtubs", "showers"):
        return Answer(getattr(plan, intent), "count", ev, "swiss")
    if intent == "apartments":
        return Answer(len(plan.apartments), "count", ev, "swiss")
    if intent == "label_count":
        rs = [r for r in plan.rooms if norm(r.name) == norm(quotes[0])]
        return Answer(len(rs), "count", _ev(path, rs, plan), "swiss")
    if intent == "room_area":
        m = re.search(r"(?:room|raum|pièce|locale) ([\w.]+) ?[\(«]", q.question, re.I)
        rs = [r for r in plan.rooms if r.number == m.group(1)]
        if not rs:
            return Answer(None, "m2", lane="swiss", note=f"declined: room {m.group(1)} not found on this floor", abstain=ABSTAIN_DECLINED)
        return Answer(round(rs[0].area, 2), "m2", _ev(path, rs, plan), "swiss")
    if intent == "label_area":
        rs = [r for r in plan.rooms if norm(r.name) == norm(quotes[0])]
        return Answer(round(sum(r.area for r in rs), 2), "m2", _ev(path, rs, plan), "swiss")
    if intent == "indoor_area":
        rs = [r for r in plan.rooms if not excluded(r.name)]
        return Answer(round(sum(r.area for r in rs), 2), "m2", _ev(path, rs, plan), "swiss")
    if intent == "apt_area":
        letter = re.search(r"(?:apartment|wohnung|appartement|appartamento|logement) ([A-Za-z]{1,2})\b", q.question, re.I).group(1).upper()
        tagged = next((r for r in plan.rooms if r.apt_tag == letter), None)
        if tagged is None:
            return Answer(None, "m2", lane="swiss", note=f"declined: apartment {letter} not found on this floor", abstain=ABSTAIN_DECLINED)
        if tagged.unit is None:
            return Answer(None, "m2", lane="swiss", note=f"declined: apartment {letter} has no unit outline", abstain=ABSTAIN_DECLINED)
        rs = [r for r in plan.rooms if r.unit == tagged.unit and not excluded(r.name)]
        return Answer(round(sum(r.area for r in rs), 2), "m2", _ev(path, rs, plan), "swiss")
    return Answer(None, lane="swiss", note="intent not recognised", abstain=ABSTAIN_DEFER)
