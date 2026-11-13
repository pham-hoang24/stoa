"""IFC lane: deterministic answers from IfcOpenShell. Handles ifc_models (.ifc/.pdf/.svg) questions.

Findings behind the choices (see docs/research/tooling-and-dataset.md):
* spaces: Qto NetFloorArea if present, else footprint area of the geometry
* walls/slabs: complete Qto sums using each quantity's unit or project unit type
* counts: spatial decomposition of the storey filtered by IFC class
"""
from __future__ import annotations

import functools
import math
import re
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as ue
import ifcopenshell.util.shape as ushape
import ifcopenshell.util.unit as uunit

from ..answer import Answer, Evidence
from ..data import Question
from ..qparse import norm, quoted

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


@functools.lru_cache(maxsize=4)
def _open(path: str):
    return ifcopenshell.open(path)


def resolve_ifc(p: Path) -> Path | None:
    """Resolve an exact twin or the dataset's `<model>_plan-NN-...` companion.

    An arbitrary filename prefix is not enough to identify a source model.
    """
    if p.suffix.lower() == ".ifc":
        return p if p.is_file() else None
    if not p.parent.is_dir():
        return None
    cands = [c for c in p.parent.iterdir() if c.is_file() and c.suffix.lower() == ".ifc"]
    exact = [c for c in cands if c.stem == p.stem]
    if exact:
        return exact[0] if len(exact) == 1 else None
    stem = re.split(r"_plan-\d+(?:-|$)", p.stem, maxsplit=1)[0]
    matches = [c for c in cands if c.stem == stem]
    return matches[0] if len(matches) == 1 else None


def _storey(f, name: str):
    n = norm(name)
    matches = [s for s in f.by_type("IfcBuildingStorey")
               if n and n in (norm(s.Name or ""), norm(s.LongName or ""))]
    return matches[0] if len(matches) == 1 else None


def _scale(f, kind: str) -> float:
    return uunit.calculate_unit_scale(f, kind)


def _qto(el, names: tuple[str, ...], unit_type: str):
    sets = ue.get_psets(el, qtos_only=True)
    for n in names:
        for props in sets.values():
            if isinstance(props.get(n), (int, float)):
                qto = el.file.by_id(props["id"])
                quantity = next((q for q in qto.Quantities if q.Name == n), None)
                unit = getattr(quantity, "Unit", None)
                scale = uunit.get_unit_scale(unit) if unit else _scale(el.file, unit_type)
                return float(props[n]) * scale
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
    q = _qto(sp, ("NetFloorArea",), "AREAUNIT")
    if q is not None and math.isfinite(q) and q >= 0:
        return q, "Qto NetFloorArea"
    a = _footprint(sp)
    return a, "footprint geometry"


def _top(els, cls: str):
    """Drop parts aggregated into an element of the same class (ArchiCAD stairs are split into hundreds of IfcStair parts)."""
    out = {}
    for e in els:
        parent = ue.get_aggregate(e)
        if parent is not None and parent.is_a(cls):
            continue
        out.setdefault(e.GlobalId, e)
    return sorted(out.values(), key=lambda e: e.GlobalId)


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


def _wording(q: str) -> str:
    for label in quoted(q):
        q = q.replace(label, " ")
    return q


def _qty(q: str) -> str:
    ql = _wording(q).casefold()
    for k in ("side", "length", "volume", "area"):
        if any(w in ql for w in QTY_WORDS[k]):
            return k
    return "count"


def _scope(question: str, qty: str):
    """Interpret explicit model scope separately from a quoted storey/room.

    Mask quoted labels before checking scope words: a floor called 'Model floor'
    must not turn an unknown-storey question into a whole-model query.
    """
    quotes = quoted(question)
    wording = _wording(question)
    model = bool(re.search(r"\b(?:model(?:s|len|l|lo)?|mudeli[st]?|modèle|malli)\b", wording, re.I))
    floor = bool(re.search(r"floor(?!\s+area)|storey|story|korrus|geschoss|etage|kerros|étage|piano", wording, re.I))
    if model:
        if floor or len(quotes) > 1:
            return None, None, None, "ambiguous model/storey scope"
        return "model", quotes[0] if quotes else "whole model", None, ""
    if len(quotes) == 1:
        return "storey", quotes[0], None, ""
    if len(quotes) == 2 and qty == "area" and _entity(wording) in (None, "IfcSpace"):
        return "room", quotes[1], quotes[0], ""
    return None, None, None, "ambiguous scope: specify a model or a named storey"


def _result(value, unit, path, scope, method, elements=(), note="") -> Answer:
    """Keep source, scope and calculation method in the existing evidence contract."""
    ev = [Evidence(str(path), f"{e.Name or e.is_a()}; scope={scope}; method={how}",
                   global_id=e.GlobalId) for e, how in elements]
    # Zero counts and abstentions still cite their source and interpreted scope.
    if not ev:
        ev = [Evidence(str(path), f"scope={scope}; method={method}")]
    return Answer(value, unit, ev, "ifc", f"scope={scope}; method={method}" + (f"; {note}" if note else ""))


def answer(q: Question, path: Path) -> Answer:
    if q.type == "text" or "ifc_bench" in q.path:
        return Answer(None, lane="ifc", note="free-form text handled by llm lane")
    qty = _qty(q.question)
    kind, name, room, error = _scope(q.question, qty)
    scope = f"{kind}: {name}" if kind else "unresolved"
    if room:
        scope += f"; room: {room}"
    if error:
        return _result(None, None, path, scope, "scope resolution", note=error)
    ifc = resolve_ifc(path)
    if ifc is None:
        # A floor SVG is a partial inventory. It cannot establish a complete
        # model/storey count or a total quantity when the IFC is unavailable.
        return _result(None, None, path, scope, "companion IFC resolution",
                       note="no unique companion IFC; complete inventory unavailable")
    f = _open(str(ifc))
    cls = _entity(_wording(q.question))
    if kind == "model":
        if cls is None:
            return _result(None, None, ifc, scope, "IFC inventory", note="unsupported entity")
        els = _top(f.by_type(cls), cls)
    else:
        st = _storey(f, name)
        if st is None:
            return _result(None, None, ifc, scope, "storey lookup",
                           note=f"storey {name!r} not found or not unique")
        if kind == "room":
            matches = [sp for sp in _in_storey(st, "IfcSpace") if norm(room) in space_label(sp)]
            if len(matches) != 1:
                return _result(None, "m2", ifc, scope, "room lookup",
                               note=f"room {room!r} not found or not unique on {name!r}")
            sp = matches[0]
            value, how = space_area(f, sp)
            if value is None or not math.isfinite(value) or value < 0:
                return _result(None, "m2", ifc, scope, how, [(sp, how)], note="room area unavailable")
            return _result(round(value, 3), "m2", ifc, scope, how, [(sp, how)])
        if qty == "area" and cls is None:
            cls = "IfcSpace"
        if cls is None:
            return _result(None, None, ifc, scope, "IFC inventory", note="unsupported entity")
        els = _in_storey(st, cls)
    if qty == "count":
        return _result(len(els), "count", ifc, scope, "IFC element inventory",
                       [(e, "IFC element inventory") for e in els])

    unit = {"length": "m", "side": "m2", "volume": "m3", "area": "m2"}[qty]
    unit_type = {"length": "LENGTHUNIT", "side": "AREAUNIT", "volume": "VOLUMEUNIT", "area": "AREAUNIT"}[qty]
    names = {"length": ("Length",), "side": ("NetSideArea",),
             "volume": ("NetVolume",), "area": ("NetArea",)}[qty]
    total, evidence, missing = 0.0, [], []
    for e in els:
        value, how = None, "quantity unavailable"
        if qty == "area" and cls == "IfcSpace":
            value, how = space_area(f, e)
        else:
            for key in names:
                value = _qto(e, (key,), unit_type)
                if value is not None:
                    how = f"Qto {key} ({unit})"
                    break
            if value is None and qty == "volume":
                try:
                    value = ushape.get_volume(ifcopenshell.geom.create_shape(_settings(), e).geometry)
                    how = "geometry volume (m3)"
                except Exception:
                    value = None
        if value is None or not math.isfinite(value) or value < 0:
            missing.append(e.GlobalId)
        else:
            total += value
        evidence.append((e, how))
    method = " + ".join(sorted({how for _, how in evidence})) or "empty IFC inventory"
    if missing:
        return _result(None, unit, ifc, scope, method, evidence,
                       note=f"incomplete total: {len(missing)}/{len(els)} elements missing {qty}")
    return _result(round(total, 3), unit, ifc, scope, method, evidence)
