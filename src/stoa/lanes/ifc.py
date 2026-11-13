"""IFC lane: deterministic answers from IfcOpenShell. Handles ifc_models (.ifc/.pdf/.svg) questions.

Findings behind the choices (see docs/research/tooling-and-dataset.md):
* spaces: Qto NetFloorArea if present, else footprint area of the geometry
* walls/slabs: Qto sums; length qty is in project length unit, area/volume are already SI
* counts: spatial decomposition of the storey filtered by IFC class
"""
from __future__ import annotations

import functools
import re
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as ue
import ifcopenshell.util.shape as ushape
import ifcopenshell.util.unit as uunit

from ..answer import Answer, Evidence
from ..data import Question
from ..qparse import has, norm, quoted

# multilingual stems (en, et, da, de, fi, sv, fr, it) -> IFC class
ENTITY_WORDS = {
    "IfcDoor": ("door", "uks", "ust", "uste", "dør", "tür", "ovi", "ovea", "dörr", "porte", "porta"),
    "IfcWindow": ("window", "aken", "akent", "akna", "vindue", "fenster", "ikkun", "fönster", "fenêtre", "finestr"),
    "IfcSpace": ("room", "ruum", "ruumi", "rum", "rummet", "raum", "räume", "huone", "pièce", "locali", "space"),
    "IfcWall": ("wall", "sein", "seina", "væg", "wand", "wände", "seinä", "vägg", "mur", "parete"),
    "IfcColumn": ("column", "post", "posti", "søjle", "stütze", "pilari", "pelare", "colonne", "pilastr"),
    "IfcStair": ("stair", "trepp", "treppi", "trappe", "treppe", "porras", "trappa", "escalier", "scala"),
    "IfcSlab": ("slab", "plaat", "dæk", "decke", "laatta", "platta", "dalle", "soletta"),
    "IfcBeam": ("beam", "tala", "talasid", "bjælke", "balken", "palkki", "balk", "poutre", "trave"),
}
QTY_WORDS = {
    "length": ("length", "pikkus", "længde", "länge", "pituus", "längd", "longueur", "lunghezza"),
    "side": ("side area", "külgpind", "sideareal", "seitenfläche"),
    "volume": ("volume", "maht", "volumen", "tilavuus", "volym", "volume"),
    "area": ("area", "pind", "areal", "fläche", "pinta-ala", "yta", "surface", "superficie", "m²"),
}
TOTAL_WORDS = ("total", "kõigi", "samlede", "alle", "all ", "gesamt", "yhteensä", "toutes", "tutti")


@functools.lru_cache(maxsize=4)
def _open(path: str):
    return ifcopenshell.open(path)


def resolve_ifc(p: Path) -> Path | None:
    """ifc_models PDF/SVG floor plans were rendered from `<model>.ifc`."""
    if p.suffix == ".ifc":
        return p
    stem = p.stem
    cands = sorted(p.parent.glob("*.ifc"), key=lambda c: -len(c.stem))
    for c in cands:
        if stem.startswith(c.stem):
            return c
    return None


def _storey(f, name: str):
    n = norm(name)
    for s in f.by_type("IfcBuildingStorey"):
        if norm(s.Name or "") == n or norm(s.LongName or "") == n:
            return s
    return None


def _scale(f, kind: str) -> float:
    try:
        return uunit.calculate_unit_scale(f, kind)
    except Exception:
        return 1.0


def _qto(el, names: tuple[str, ...]):
    for _, props in ue.get_psets(el, qtos_only=True).items():
        for n in names:
            if isinstance(props.get(n), (int, float)):
                return float(props[n])
    return None


@functools.lru_cache(maxsize=8)
def _settings():
    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)
    return s


def _footprint(el) -> float | None:
    try:
        shp = ifcopenshell.geom.create_shape(_settings(), el)
        return float(ushape.get_footprint_area(shp.geometry))
    except Exception:
        return None


def space_area(f, sp) -> tuple[float | None, str]:
    q = _qto(sp, ("NetFloorArea",))
    if q is not None and q > 0:
        return q * _scale(f, "AREAUNIT"), "Qto NetFloorArea"
    a = _footprint(sp)
    return a, "footprint geometry"


def _top(els, cls: str):
    """Drop parts aggregated into an element of the same class (ArchiCAD stairs are split into hundreds of IfcStair parts)."""
    out = []
    for e in els:
        parent = ue.get_aggregate(e)
        if parent is not None and parent.is_a(cls):
            continue
        out.append(e)
    return out


def _in_storey(storey, cls: str):
    return _top([e for e in ue.get_decomposition(storey) if e.is_a(cls)], cls)


def space_label(sp) -> list[str]:
    """Labels that questions use: 'LongName (Name)', also bare forms."""
    ln, n = (sp.LongName or "").strip(), (sp.Name or "").strip()
    return [norm(f"{ln} ({n})"), norm(f"{n} ({ln})"), norm(n), norm(ln)]


def _entity(q: str) -> str | None:
    ql = q.casefold()
    best, pos = None, 10**9
    for cls, words in ENTITY_WORDS.items():
        for w in words:
            i = ql.find(w)
            if i != -1 and i < pos:
                best, pos = cls, i
    return best


def _qty(q: str) -> str:
    ql = q.casefold()
    for k in ("side", "length", "volume", "area"):
        if any(w in ql for w in QTY_WORDS[k]):
            return k
    return "count"


def answer(q: Question, path: Path) -> Answer:
    ifc = resolve_ifc(path)
    if ifc is None:
        return _svg_answer(q, path)
    f = _open(str(ifc))
    quotes = quoted(q.question)

    if q.type == "text" or "ifc_bench" in q.path:
        return Answer(None, lane="ifc", note="free-form text handled by llm lane")

    # --- single room net area: two quotes (room, storey)
    if len(quotes) >= 2:
        room, storey_name = quotes[0], quotes[1]
        st = _storey(f, storey_name)
        if st is None:
            return Answer(None, lane="ifc", note=f"storey {storey_name!r} not found")
        for sp in _in_storey(st, "IfcSpace"):
            if norm(room) in space_label(sp):
                a, how = space_area(f, sp)
                return Answer(round(a, 3) if a is not None else None, "m2", [Evidence(str(ifc), f"{room} ({how})", global_id=sp.GlobalId)], "ifc")
        return Answer(None, lane="ifc", note=f"room {room!r} not on {storey_name!r}")

    if len(quotes) != 1:
        return Answer(None, lane="ifc", note="cannot find storey in question")
    st = _storey(f, quotes[0])
    qty, cls = _qty(q.question), _entity(q.question)
    if st is None:
        if cls and qty == "count" and has(q.question, "model", "mudel", "modell", "modèle", "modello", "malli", "modellen"):  # quote is the model name
            els = _top(f.by_type(cls), cls)
            return Answer(len(els), "count", [Evidence(str(ifc), e.Name or "", global_id=e.GlobalId) for e in els[:200]], "ifc")
        return Answer(None, lane="ifc", note=f"storey {quotes[0]!r} not found")

    # "total net floor area of all rooms" -> area of spaces
    if qty == "area" and cls in (None, "IfcSpace"):
        tot, ev = 0.0, []
        for sp in _in_storey(st, "IfcSpace"):
            a, _ = space_area(f, sp)
            if a:
                tot += a
                ev.append(Evidence(str(ifc), sp.Name or "", global_id=sp.GlobalId))
        return Answer(round(tot, 3), "m2", ev, "ifc")
    if cls is None:
        return Answer(None, lane="ifc", note="entity not recognised")
    els = _in_storey(st, cls)
    if qty == "count":
        return Answer(len(els), "count", [Evidence(str(ifc), e.Name or "", global_id=e.GlobalId) for e in els[:200]], "ifc")

    names = {"length": ("Length",), "side": ("NetSideArea", "GrossSideArea"), "volume": ("NetVolume", "GrossVolume"), "area": ("NetArea", "GrossArea")}[qty]
    unit = {"length": "LENGTHUNIT", "side": "AREAUNIT", "volume": "VOLUMEUNIT", "area": "AREAUNIT"}[qty]
    # prefer the Net* variant consistently; count how many elements had it
    tot, ev = 0.0, []
    for e in els:
        v = _qto(e, names[:1]) if qty != "length" else _qto(e, names)
        if v is None and qty != "length":
            v = _qto(e, names)
        if v is None and qty == "volume":
            try:
                tot += ushape.get_volume(ifcopenshell.geom.create_shape(_settings(), e).geometry)
                ev.append(Evidence(str(ifc), f"{e.Name} (geometry)", global_id=e.GlobalId))
                continue
            except Exception:
                v = None
        if v is not None:
            tot += v * _scale(f, unit)
            ev.append(Evidence(str(ifc), e.Name or "", global_id=e.GlobalId))
    unit_s = {"length": "m", "side": "m2", "volume": "m3", "area": "m2"}[qty]
    return Answer(round(tot, 3), unit_s, ev, "ifc")


def _svg_answer(q: Question, path: Path) -> Answer:
    """No IFC shipped (FZK): count element groups in the SVG twin of the floor plan (class="IfcXxx")."""
    svg = path if path.suffix == ".svg" else path.with_suffix(".svg")
    if not svg.exists():
        return Answer(None, lane="ifc", note=f"no IFC or SVG for {path.name}")
    cls, qty = _entity(q.question), _qty(q.question)
    if cls is None or qty != "count":
        return Answer(None, lane="ifc", note="svg fallback only counts elements")
    names = {cls} | ({"IfcWallStandardCase"} if cls == "IfcWall" else set())
    txt = svg.read_text(encoding="utf-8", errors="ignore")
    n = sum(len(re.findall(rf'class="{c}"', txt)) for c in names)
    return Answer(n, "count", [Evidence(str(svg), f"{cls} groups in SVG")], "ifc", "from SVG (no IFC)")
