"""Connect complete IFC inventories to their retained drawing projections.

At the Evidence boundary, PDF and SVG boxes are (x0, y0, x1, y1) in
72-point rendered-page coordinates, with origin at the top left and y down.
SVG viewBox offsets, physical dimensions, transforms and arcs are handled by
MuPDF. A PDF sibling must have the same viewport; an incompatible page is never
stretched to fit. Entries without a projection retain their IFC citation.
"""
from __future__ import annotations

import copy
import functools
import math
import xml.etree.ElementTree as ET
from pathlib import Path

from .. import data
from ..answer import Answer


def _stamp(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return str(path.resolve()), stat.st_mtime_ns, stat.st_size


@functools.lru_cache(maxsize=64)
def _index(path: str, mtime: int, size: int):
    root = ET.parse(path).getroot()
    groups = {}

    def visit(node, ancestors):
        guid = node.get("data-guid")
        if guid:
            groups.setdefault(guid, []).append((ancestors, node))
        for child in node:
            visit(child, (*ancestors, node))

    visit(root, ())
    return root, groups


@functools.lru_cache(maxsize=32)
def _geometry(path: str, mtime: int, size: int):
    import pymupdf

    root, groups = _index(path, mtime, size)
    with pymupdf.open(path) as doc:
        viewport = doc[0].rect
    boxes = {}
    for guid, fragments in groups.items():
        union = None
        for ancestors, node in fragments:
            isolated = ET.Element(root.tag, root.attrib)
            # Definitions and styles may be referenced by retained geometry.
            for child in root:
                if child.tag.rsplit("}", 1)[-1] in ("defs", "style"):
                    isolated.append(copy.deepcopy(child))
            parent = isolated
            for ancestor in ancestors[1:]:  # root is already present
                parent = ET.SubElement(parent, ancestor.tag, ancestor.attrib)
            fragment = copy.deepcopy(node)
            # A nested product has its own identity, not its parent's geometry.
            for container in fragment.iter():
                for child in list(container):
                    if child.get("data-guid") not in (None, guid):
                        container.remove(child)
            parent.append(fragment)
            with pymupdf.open(stream=ET.tostring(isolated), filetype="svg") as doc:
                for drawing in doc[0].get_drawings():
                    rect = drawing["rect"]
                    if not all(math.isfinite(v) for v in rect):
                        continue
                    # Include the stroke and allow horizontal/vertical lines.
                    pad = max(float(drawing.get("width") or 0) / 2, 0)
                    rect = (rect + (-pad, -pad, pad, pad)) & viewport
                    if rect.is_empty:
                        continue
                    union = rect if union is None else union | rect
        if union is not None:
            boxes[guid] = tuple(union)
    return tuple(viewport), boxes


def _choose_view(selected: Path, model: Path, ids: set[str]) -> Path | None:
    if selected.suffix.lower() in (".pdf", ".svg"):
        svg = selected.with_suffix(".svg")
        return svg if svg.is_file() else None
    exact = model.with_suffix(".svg")
    candidates = [exact] if exact.is_file() else []
    for kind in ("plan", "elevation", "section"):
        candidates.extend(sorted(model.parent.glob(f"{model.stem}_{kind}-*.svg")))
    # For a model input, choose the available view covering the most
    # contributors. A selected drawing always keeps its own view instead.
    best, overlap = None, 0
    for svg in candidates:
        try:
            _, groups = _index(*_stamp(svg))
        except (ET.ParseError, OSError):
            continue
        covered = len(ids.intersection(groups))
        if covered > overlap:
            best, overlap = svg, covered
    return best


def attach(result: Answer, selected: Path) -> Answer:
    """Add drawing boxes without changing the answer or its GlobalId inventory.

    One entry remains per contributing GlobalId. A visible entry cites the PDF
    (or SVG when no PDF exists), page 0, in top-left rendered-page points.
    Off-view entries keep the IFC source, GlobalId and no bounding box. Their
    labels and the answer note explicitly distinguish inventory from coverage.
    """
    elements = [e for e in result.evidence if e.global_id]
    if result.value is None or not elements:
        return result
    model = Path(elements[0].file)
    ids = {e.global_id for e in elements}
    try:
        svg = _choose_view(selected, model, ids)
        if svg is None:
            raise ValueError("no retained SVG view for the selected source")
        viewport, boxes = _geometry(*_stamp(svg))
        drawing = svg.with_suffix(".pdf")
        if drawing.is_file():
            import pymupdf

            with pymupdf.open(drawing) as doc:
                page = doc[0]
                if (page.rotation or page.cropbox.x0 or page.cropbox.y0
                        or any(abs(a - b) > 0.1 for a, b in zip(page.rect, viewport))):
                    raise ValueError("PDF viewport does not match retained SVG")
        else:
            drawing = svg
        _, groups = _index(*_stamp(svg))
    except Exception as exc:
        # Projection failure cannot discard a verified model count or its IDs.
        for e in elements:
            e.label += "; projection unavailable"
        result.note += f"; overlay unavailable: {exc}"
        return result

    visible = 0
    for e in elements:
        bbox = boxes.get(e.global_id)
        if bbox is None:
            reason = "not present in displayed view" if e.global_id not in groups else "no visible geometry in displayed view"
            e.label += f"; {reason} ({drawing.name})"
            continue
        visible += 1
        try:
            reference = str(drawing.resolve().relative_to(data.ROOT.resolve()))
        except ValueError:
            reference = str(drawing.resolve())
        e.file, e.page, e.bbox = reference, 0, bbox
        e.label += f"; IFC source={model.name}; projection={svg.name}; bbox=page points"
    result.note += (f"; IFC source={model.name}; selected source={selected.name}; view={drawing.name}"
                    f"; visible geometry={visible}/{len(elements)}"
                    f"; {len(elements) - visible} contributing elements without visible geometry in this view")
    return result
