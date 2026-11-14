"""Bounded schedule questions over native PDF rows; no model calls or OCR."""
from __future__ import annotations

import re
from pathlib import Path

from .. import data
from ..answer import ABSTAIN_DECLINED, Answer, Evidence
from ..data import Question
from .schedule_tables import Book, Row, clean, load


def _reference(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(data.ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def _reply(path, value, unit=None, rows=(), reason=""):
    evidence = [Evidence(_reference(path), f"{r.kind}: {r.values.get('id', '')}",
                         page=r.page, bbox=r.bbox) for r in rows]
    return Answer(value, unit, evidence, "schedules",
                  "method=native PDF schedule rows; quantities as printed" + (f"; {reason}" if reason else ""),
                  abstain=ABSTAIN_DECLINED if value is None else None)


def _dimension(value):
    return re.sub(r"\s+", "", value).replace("′", "'").replace("″", '"')


def _area(row):
    value = row.values.get("area", "")
    match = re.fullmatch(r"([\d,]+(?:\.\d+)?)\s*(?:SF|SQ\.?\s*FT|FT2)", value, re.I)
    return float(match[1].replace(",", "")) if match else None


def _quantity(rows):
    return sum(int(r.values.get("quantity", "1")) for r in rows)


def _select(book: Book, kind: str, text: str, original: str):
    rows = book.rows.get(kind, [])
    if kind in book.errors:
        raise ValueError(book.errors[kind])
    if not rows:
        raise ValueError("no readable schedule of the requested kind; scans and plan-symbol counts are unsupported")
    selected = list(rows)
    constrained = False
    room = re.search(r"\broom\s+(\d+)\b", text)
    if room:
        key = "id" if kind == "rooms" else "room"
        selected = [r for r in selected if r.values.get(key) == room[1]]
        constrained = True
    identifier = re.search(r"\bdoor\s+(\d+\.[a-z]\d*)\b", text)
    if identifier and kind != "rooms":
        selected = [r for r in selected if r.values["id"].lower() == identifier[1]]
        constrained = True
    span = re.search(r"\b(\d+\.[a-z]\d+)\s*-\s*(\d+\.[a-z]\d+)\b", text)
    if span and kind != "rooms":
        keys = {r.values["id"].lower() for r in rows}
        if span[1] not in keys or span[2] not in keys or span[1] > span[2]:
            raise ValueError("door range is absent or ambiguous")
        selected = [r for r in selected if span[1] <= r.values["id"].lower() <= span[2]]
        constrained = True
    if kind in ("door_types", "doors"):
        codes = re.findall(r"\bU\d+(?:-[A-Z]{1,2})?\b" if kind == "door_types" else r"\b[A-Z]\d+\b", original.upper())
        if codes:
            field = "id" if kind == "door_types" else "door_type"
            selected = [r for r in selected if r.values.get(field) in codes]
            constrained = True
    elif kind == "windows":
        match = re.search(r"\btypes?\s+([A-Z]{2}(?:\s*(?:,|and)\s*[A-Z]{2})*)\b", original, re.I)
        if match:
            codes = re.findall(r"\b[A-Z]{2}\b", match[1].upper())
            selected = [r for r in selected if r.values["id"] in codes]
            constrained = True
    else:
        code = re.search(r"\b([FBCW]\d+)\b", original.upper())
        if code:
            if "four walls" in text:
                selected = [r for r in selected if all(r.values.get(k) == code[1] for k in ("north", "south", "east", "west"))]
            else:
                field = "floor" if code[1].startswith("F") else "base" if code[1].startswith("B") else "ceiling" if code[1].startswith("C") else "north"
                selected = [r for r in selected if code[1] in re.findall(r"\b[A-Z]\d+\b", r.values.get(field, ""))]
            constrained = True
        if "named" in text or "labelled" in text:
            names = {r.values.get("name", "") for r in rows if r.values.get("name")}
            matches = [n for n in names if re.search(r"(?<!\w)" + re.escape(n.lower()) + r"(?!\w)", text)]
            if len(matches) != 1:
                raise ValueError("room label is absent or ambiguous")
            selected = [r for r in selected if r.values.get("name") == matches[0]]
            constrained = True
        if "locker" in text and not room:
            selected = [r for r in selected if "LOCKER" in r.values.get("name", "")]
            constrained = True
    materials = re.findall(r"\b(?:WD|STL|AL|GL)-\d+\b", original.upper())
    if materials:
        field = "frame_material" if "frame" in text else "door_material"
        selected = [r for r in selected if any(k in re.findall(r"[A-Z]+-\d+", r.values.get(field, "")) for k in materials)]
        constrained = True
    note = re.search(r"\bnote\s+([a-z])\b", text)
    if note:
        selected = [r for r in selected if re.fullmatch(r"[A-Z](?:\s*,\s*[A-Z])*", r.values.get("notes", ""))
                    and note[1].upper() in r.values["notes"]]
        constrained = True
    dims = re.findall(r"\d+'\s*-\s*\d+(?:\s+\d+/\d+)?\s*\"", original)
    if dims:
        fields = ("width", "height") if len(dims) == 2 else ("height",) if re.search(r"high|height", text) else ("width",)
        if len(dims) != len(fields):
            raise ValueError("ambiguous dimension filter")
        selected = [r for r in selected if all(_dimension(r.values.get(k, "")) == _dimension(d) for k, d in zip(fields, dims))]
        constrained = True
    floor = re.search(r"\b(\d+(?:st|nd|rd|th)) floor\b", text)
    if floor:
        selected = [r for r in selected if floor[0].upper() in r.values.get("description", "")]
        constrained = True
    if kind == "door_types" and not re.search(r"\bU\d+", original, re.I):
        if "description starts" in text:
            match = re.search(r"starts with ['\"]([^'\"]+)['\"]", text)
            if not match:
                raise ValueError("description prefix missing")
            selected = [r for r in selected if r.values.get("description", "").lower().startswith(match[1])]
            constrained = True
        elif not re.search(r"all type marks|items in total", text):
            # Match explicit description words present in the schedule, rather
            # than translating door brands/types from a memorized building.
            vocabulary = {w.lower() for r in rows for w in re.findall(r"[A-Za-z]{3,}", r.values.get("description", ""))}
            ignore = {"door", "doors", "type", "types", "floor", "total", "count", "with", "and", "the", "are", "scheduled"}
            terms = set(re.findall(r"[a-z]{3,}", text)) & (vocabulary - ignore)
            if terms:
                selected = [r for r in selected if all(re.search(r"\b" + re.escape(w) + r"\b", r.values.get("description", ""), re.I) for w in terms)]
                constrained = True
    return rows, selected, constrained


def _expand(book, value, namespace):
    if "legend" in book.errors:
        raise ValueError(book.errors["legend"])
    codes = re.findall(r"\b[A-Z]\d+\b", value)
    expanded, evidence = [], []
    for code in codes:
        definition = book.legends.get(namespace + ":" + code)
        if definition is None:
            raise ValueError(f"definition for {code} is not available")
        expanded.append(definition[0])
        evidence.append(definition[1])
    return value + " - " + " and ".join(expanded), evidence


def answer(q: Question, path: Path) -> Answer:
    if path.suffix.lower() != ".pdf":
        return _reply(path, None, reason="schedule lane supports native-text PDFs only")
    book = load(path)
    text = q.question.casefold()
    mark = re.search(r"\bsheet\s+([a-z]-?\d{3})\b", text)
    if mark and mark[1].replace("-", "").upper() not in book.text.replace("-", "").upper():
        return _reply(path, None, reason="requested sheet is not identified in the selected drawing")
    if "window" in text:
        kind = "windows"
    elif "door" in text or (book.rows.get("door_types") and re.search(r"\bU\d+\b", q.question, re.I)):
        kind = "door_types" if book.rows.get("door_types") else "doors"
    elif re.search(r"room|finish|area|locker", text):
        kind = "rooms"
    else:
        return _reply(path, None, reason="unsupported schedule question")
    try:
        all_rows, rows, constrained = _select(book, kind, text, q.question)
        count = "how many" in text
        area = kind == "rooms" and "area" in text
        if area:
            if q.unit not in (None, "ft2") or re.search(r"m²|square met|\bm2\b", text):
                raise ValueError("schedule areas are printed in ft2; requested unit conversion is unsupported")
            known = [r for r in rows if _area(r) is not None]
            if "largest" in text:
                if not known:
                    raise ValueError("no printed room areas")
                best = max(known, key=_area)
                return _reply(path, f"Room {best.values['id']} {best.values.get('name', '')} ({_area(best):g} SF)", rows=[best])
            if len(known) != len(rows) and not re.search(r"area listed|area of all rooms that have", text):
                raise ValueError("incomplete room areas; some schedule entries have no numeric area")
            if not rows:
                raise ValueError("requested rooms not found")
            total = sum(_area(r) for r in known)
            if count:
                return _reply(path, f"{len(rows)} rooms, {total:g} SF", rows=known)
            return _reply(path, round(total, 2), "ft2", known)
        if count:
            if kind == "windows" and "units" in text and "n-wide" in text:
                factors = [re.search(r"\b(\d+)-WIDE\b", r.values.get("description", "")) for r in rows]
                if any(m is None for m in factors):
                    raise ValueError("window assembly width multiplier is unavailable")
                value = sum(int(r.values["quantity"]) * int(m[1]) for r, m in zip(rows, factors))
            else:
                plain = re.sub(r"\([^)]*\)", " ", text)
                plain = clean(plain)
                if not constrained and not re.search(r"in total|total|all |how many (?:doors|windows|rooms|items) are (?:listed|scheduled)", plain):
                    raise ValueError("unsupported count filter")
                value = _quantity(rows)
            return _reply(path, value, "count", rows or all_rows,
                          "scheduled quantities; assemblies are not expanded unless explicitly requested")
        if not rows:
            raise ValueError("requested schedule identifier not found")
        if "width" in text and "height" in text:
            fields = ("width", "height")
        else:
            field = next((key for phrase, key in [
                ("hardware", "hardware"), ("frame material", "frame_material"),
                ("door material", "door_material"), ("fire rating", "fire_rating"),
                ("north wall finish", "north"), ("south wall finish", "south"),
                ("east wall finish", "east"), ("west wall finish", "west"),
                ("floor finish", "floor"), ("ceiling finish", "ceiling"),
                ("width", "width"), ("height", "height"), ("door type", "door_type"),
            ] if phrase in text), None)
            if field is None:
                raise ValueError("unsupported schedule attribute")
            fields = (field,)
        values = {tuple(r.values.get(f, "") for f in fields) for r in rows}
        if len(values) != 1 or any(not v for v in next(iter(values))):
            raise ValueError("requested attribute is missing or not unique across the selected rows")
        value = next(iter(values))
        if len(fields) == 2:
            result = f"{value[0]} wide x {value[1]} high"
        else:
            result = value[0]
            if fields[0] in ("floor", "ceiling", "north", "south", "east", "west", "door_type"):
                namespace = "door_type" if fields[0] == "door_type" else "finish"
                result, definitions = _expand(book, result, namespace)
                rows = [*rows, *definitions]
        return _reply(path, result, rows=rows)
    except ValueError as exc:
        return _reply(path, None, reason=str(exc))
