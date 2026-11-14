"""Native PDF schedule tables, normalized to the displayed page coordinates.

Only vector-line tables and selectable text are used. Layout-model inference
and OCR are disabled. Source files are never modified. Boxes use top-left
72-point rendered-page coordinates, including originally rotated pages.
"""
from __future__ import annotations

import functools
import inspect
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf


def clean(value) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


@dataclass(frozen=True)
class Row:
    kind: str
    values: dict[str, str]
    page: int
    bbox: tuple[float, float, float, float]


@dataclass
class Book:
    rows: dict[str, list[Row]] = field(default_factory=dict)
    legends: dict[str, tuple[str, Row]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    text: str = ""


ALIASES = {
    "door number": "id", "mark": "id", "room name": "name", "from room: name": "name",
    "room number": "room", "width": "width", "height": "height", "door type": "door_type",
    "frame type": "frame_type", "door material": "door_material", "frame material": "frame_material",
    "notes": "notes", "area": "area", "floor finish": "floor", "base finish": "base",
    "ceiling finish": "ceiling", "north wall": "north", "south wall": "south",
    "east wall": "east", "west wall": "west", "count": "quantity", "type": "description",
    "fire rating": "fire_rating", "type mark": "family",
}


def _header(table):
    raw = table.extract()
    headers = []
    for i, cells in enumerate(raw[:5]):
        words = [clean(v).lower() for v in cells]
        if any(len(v) > 100 for v in words):
            continue  # enclosing page borders are not schedule tables
        if sum(w in ALIASES or "hardware" in w for w in words if w) >= 2:
            headers.append(i)
    if not headers:
        return None
    end = max(headers)
    labels = {clean(c).lower() for i in headers for c in raw[i] if c}
    title = " ".join(clean(c).lower() for row in raw[:end + 1] for c in row if c)
    if {"area", "room number", "floor finish"} <= labels:
        kind = "rooms"
    elif {"count", "type mark", "width", "height"} <= labels:
        kind = "windows" if "window schedule" in title else "door_types" if "door schedule" in title else None
    elif "door number" in labels or ("mark" in labels and "door type" in labels):
        kind = "doors"
    else:
        kind = None
    if kind is None:
        return None
    columns = {}
    for col in range(len(raw[end])):
        for rownum in headers:
            label = clean(raw[rownum][col]).lower()
            key = ALIASES.get(label)
            if "hardware" in label:
                key = "hardware"
            if label == "type mark" and kind in ("windows", "door_types"):
                key = "id"
            if label == "room number" and kind == "rooms":
                key = "id"
            if label in ("matl", "material"):
                parent = ""
                for upper in raw[:rownum]:
                    for c in upper[:col + 1]:
                        if clean(c):
                            parent = clean(c).lower()
                key = "frame_material" if parent == "frame" else "door_material" if parent == "door" else None
            if key:
                columns[col] = key
    if "id" not in columns.values():
        return None
    return kind, end, columns


def _records(table, kind, start, columns, page):
    rows = []
    id_col = next(i for i, key in columns.items() if key == "id")
    raw = table.extract()
    for i in range(start, len(raw)):
        cells = raw[i]
        if not any(clean(c) for c in cells):
            continue
        ids = (cells[id_col] or "").splitlines()
        if not ids or not all(re.fullmatch(r"[\w.-]+", clean(v)) for v in ids):
            raise ValueError("unreadable schedule row identifier")
        # Line detection can merge adjacent rows. Split only when every field
        # has an unambiguous one-to-one correspondence with the printed IDs.
        split = {}
        for col, key in columns.items():
            value = cells[col] or ""
            parts = value.splitlines()
            if len(ids) == 1:
                split[key] = [clean(value)]
            elif not value:
                split[key] = [""] * len(ids)
            elif len(parts) == len(ids):
                split[key] = [clean(v) for v in parts]
            else:
                raise ValueError("ambiguous merged schedule rows")
        for n in range(len(ids)):
            values = {key: parts[n] for key, parts in split.items()}
            if kind in ("windows", "door_types") and not re.fullmatch(r"\d+", values.get("quantity", "")):
                raise ValueError("missing or invalid scheduled quantity")
            rows.append(Row(kind, values, page, tuple(table.rows[i].bbox)))
    return rows


def _table_rows(page, tables, book):
    for table in tables:
        header = _header(table)
        if header is None:
            continue
        kind, end, columns = header
        parts = [(table, end + 1)]
        if end + 1 == len(table.rows):
            # Revit exports can leave a small gap between headers and body.
            followers = [t for t in tables if t is not table
                         and len(t.rows[0].cells) == len(table.rows[-1].cells)
                         and abs(t.bbox[0] - table.bbox[0]) < 3
                         and abs(t.bbox[2] - table.bbox[2]) < 3
                         and 0 <= t.bbox[1] - table.bbox[3] <= max(50, table.bbox[3] - table.bbox[1])]
            if followers:
                parts.append((min(followers, key=lambda t: t.bbox[1]), 0))
        try:
            records = [r for t, start in parts for r in _records(t, kind, start, columns, page.number)]
            if not records:
                raise ValueError("schedule body unavailable")
            book.rows.setdefault(kind, []).extend(records)
        except ValueError as exc:
            book.errors[kind] = str(exc)


def _legends(page, tables, book):
    for table in tables:
        for i, cells in enumerate(table.extract()):
            cells = [clean(c) for c in cells]
            if len(cells) == 2 and re.fullmatch(r"[BCFW]\d+", cells[0]) and cells[1]:
                key, value = "finish:" + cells[0], cells[1]
            elif len(cells) == 3 and cells[0] in ("DOOR", "FRAME", "NOTES") and cells[1] and cells[2]:
                key, value = cells[0].lower() + ":" + cells[1], cells[2]
            else:
                continue
            row = Row("legend", {"id": key}, page.number, tuple(table.rows[i].bbox))
            if key in book.legends and book.legends[key][0] != value:
                book.errors["legend"] = f"conflicting legend definitions: {key}"
            book.legends[key] = value, row
    # Door-type captions are native text next to the drawn door symbols.
    codes = {r.values.get("door_type", "") for r in book.rows.get("doors", [])}
    anchors = {code: page.search_for(f"DOOR TYPE {code}") for code in codes - {"", "-"}}
    for code in codes - {"", "-"}:
        hits = anchors[code]
        if len(hits) != 1:
            continue
        anchor = hits[0]
        neighbors = [r.x0 - 2 for rectangles in anchors.values() for r in rectangles
                     if abs(r.y0 - anchor.y0) < 3 and r.x0 > anchor.x0]
        right = min([anchor.x0 + 160, *neighbors])
        region = pymupdf.Rect(anchor.x0, anchor.y1, right, anchor.y1 + 35)
        caption = clean(page.get_textbox(region))
        if caption and not re.search(r"DOOR TYPE|FRAME TYPE", caption):
            row = Row("legend", {"id": code}, page.number, tuple(region & page.rect))
            book.legends["door_type:" + code] = caption, row


@functools.lru_cache(maxsize=8)
def _load(path: str, mtime: int, size: int) -> Book:
    book = Book()
    with pymupdf.open(path) as doc:
        for page in doc:
            page.remove_rotation()
            book.text += " " + " ".join(w[4] for w in page.get_text("words"))
            kwargs = {"strategy": "lines"}
            # Older PyMuPDF versions already use line-based detection only.
            if "use_layout" in inspect.signature(pymupdf.table.find_tables).parameters:
                kwargs["use_layout"] = False
            tables = page.find_tables(**kwargs).tables
            _table_rows(page, tables, book)
            _legends(page, tables, book)
    for kind, rows in book.rows.items():
        keys = [r.values["id"] for r in rows]
        if len(keys) != len(set(keys)):
            book.errors[kind] = "duplicate schedule identifiers; specify a unique schedule/page"
    return book


def load(path: Path) -> Book:
    stat = path.stat()
    return _load(str(path.resolve()), stat.st_mtime_ns, stat.st_size)
