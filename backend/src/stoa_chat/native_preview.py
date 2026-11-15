"""Plan-view previews for native IFC and DXF uploads, drawn from entity geometry.

The preview of a native source is a top-down plan. Its page frame is the
source XY plane with the y axis negated (image rows grow downwards), in source
units: DXF modelspace units, IFC world metres. A page's ``origin`` is the frame
position of preview pixel (0, 0), and ``width``/``height`` cover the whole
image, so ``transform`` in the descriptor has the same meaning as for rasters.

Every highlight box comes from the XY extent of the geometry drawn for that
entity on that page, in the same frame. Entities without drawable geometry
(for example IfcBuildingStorey, or TEXT with no extent) are not given boxes.

Geometry is computed lazily on first request in a background thread, bounded
by an element cap and a time budget, and cached on disk keyed by the asset's
SHA-256. Callers never hold the store lock while this work runs.
"""
import json
import math
import os
import threading
import time
import unicodedata
import uuid
from pathlib import Path

import cv2
import numpy as np

VERSION = 1
MAX_SIDE = 1600
MARGIN = 0.03
IFC_TIME_BUDGET = 120.0
IFC_ELEMENT_CAP = 25_000
DXF_TIME_BUDGET = 60.0
DXF_ENTITY_CAP = 200_000

# Drawn bottom to top. Colours are BGR: (fill, outline); None fill = outline only.
IFC_LAYERS = [
    ('slab', ('IfcSlab', 'IfcRoof', 'IfcCovering'), (228, 230, 230), (175, 178, 178)),
    ('space', ('IfcSpace',), (238, 246, 250), (190, 200, 205)),
    ('frame', ('IfcBeam', 'IfcMember', 'IfcPlate'), None, (150, 150, 150)),
    ('stair', ('IfcStair', 'IfcStairFlight', 'IfcRamp', 'IfcRampFlight', 'IfcRailing'), (215, 215, 215), (110, 110, 110)),
    ('wall', ('IfcWall', 'IfcCurtainWall', 'IfcColumn'), (70, 74, 70), (40, 44, 40)),
    ('window', ('IfcWindow',), (235, 200, 140), (170, 110, 40)),
    ('door', ('IfcDoor',), (150, 190, 120), (60, 110, 40)),
]

_lock = threading.Lock()
_jobs = {}


class PreviewUnavailable(ValueError):
    pass


def cache_dir(drawing, root):
    return Path(root) / f"{drawing['sha256']}-v{VERSION}"


def plan(drawing, root, wait=False):
    """Return the cached plan index, or start building it.

    Result: {'status': 'ready', 'pages': [...], 'entities': {...}, ...},
    {'status': 'unavailable', 'reason': ...} or, when not waiting,
    {'status': 'pending'} while the background job runs.
    """
    if drawing['format'] not in {'ifc', 'dxf'}:
        return {'status': 'unavailable', 'reason': 'Plan views are built only for IFC and DXF sources'}
    target = cache_dir(drawing, root)
    index = target / 'plan.json'
    with _lock:
        job = _jobs.get(str(target))
        if job is None and not index.exists():
            job = threading.Thread(target=_build, args=(drawing['format'], Path(drawing['path']), target),
                                   name='native-preview-' + drawing['sha256'][:12], daemon=True)
            _jobs[str(target)] = job
            job.start()
    if job is not None:
        if not wait:
            return {'status': 'pending'}
        job.join()
    try:
        return json.loads(index.read_text())
    except (OSError, ValueError):
        return {'status': 'unavailable', 'reason': 'The plan view could not be stored'}


def page_png(drawing, page, root):
    result = plan(drawing, root, wait=True)
    if result['status'] != 'ready':
        raise PreviewUnavailable(result.get('reason', 'No plan view'))
    if not any(p['page'] == page for p in result['pages']):
        raise PreviewUnavailable('Source page does not exist')
    return (cache_dir(drawing, root) / f'page-{page}.png').read_bytes()


def page_evidence(drawing, page):
    """The shared descriptor fields of native.page_evidence for a plan page."""
    return {'drawing_id': drawing['id'], 'page': page['page'], 'source_width': page['width'],
            'source_height': page['height'], 'source_origin': page['origin'], 'source_units': page['units'],
            'original_url': drawing['asset_url'],
            'preview_url': drawing['asset_url'].replace('/assets/', '/previews/') + '/' + str(page['page'])}


def attach(answer, drawings, root):
    """Add page/bbox/preview fields to native entity evidence from the plan view.

    Only evidence that names an entity drawn on a plan page gets a box; that box
    is the extent of the entity's drawn geometry. Storeys get their page only.
    """
    sources = {d['id']: d for d in drawings if d.get('format') in {'ifc', 'dxf'}}
    wanted = {e.get('drawing_id') for e in answer.get('evidence', []) if e.get('entity_id') is not None and 'page' not in e}
    for drawing_id in wanted & set(sources):
        drawing = sources[drawing_id]
        try:
            result = plan(drawing, root, wait=True)
        except Exception:
            continue
        if result.get('status') != 'ready':
            continue
        pages = {p['page']: p for p in result['pages']}
        for evidence in answer['evidence']:
            if evidence.get('drawing_id') != drawing_id or 'page' in evidence:
                continue
            entity = evidence.get('entity_id')
            box = result['entities'].get(entity)
            if box is not None and 'coverage' in evidence:
                # A whole-inventory citation (e.g. a zero count) names one entity
                # only as an anchor; boxing it would suggest it is the answer.
                evidence.update(page_evidence(drawing, pages[box[0]]))
            elif box is not None:
                evidence.update(page_evidence(drawing, pages[box[0]]), bbox=box[1:],
                                geometry='Extent of the entity geometry drawn in the plan view')
            elif entity in result.get('page_entities', {}):
                evidence.update(page_evidence(drawing, pages[result['page_entities'][entity]]))
    return answer


def _build(format, path, target):
    started = time.monotonic()
    try:
        try:
            pages, images, entities, extra = (_ifc if format == 'ifc' else _dxf)(path)
            result = {'status': 'ready', 'pages': pages, 'entities': entities, **extra}
        except PreviewUnavailable as exc:
            images, result = {}, {'status': 'unavailable', 'reason': str(exc)}
        except Exception as exc:  # malformed geometry must never break the chat
            images, result = {}, {'status': 'unavailable',
                                  'reason': f'The plan view could not be drawn from this file ({type(exc).__name__})'}
        result['seconds'] = round(time.monotonic() - started, 2)
        target.mkdir(parents=True, exist_ok=True)
        for number, image in images.items():
            _write(target / f'page-{number}.png', cv2.imencode('.png', image)[1].tobytes())
        _write(target / 'plan.json', json.dumps(result, allow_nan=False).encode())
    except Exception:
        pass  # storage vanished (chat deleted / server stopped); next request retries
    finally:
        with _lock:
            _jobs.pop(str(target), None)


def _write(path, content):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex)
    temporary.write_bytes(content)
    os.replace(temporary, path)


class Frame:
    """Source XY → frame (x, -y) → preview pixels, with one uniform scale."""

    def __init__(self, x0, y0, x1, y1, units):
        width, height = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
        size = max(width, height)
        if size <= 1e-9:
            size = width = height = 1.0
        pad = size * MARGIN
        self.scale = (MAX_SIDE - 1) / (size + 2 * pad)
        self.width_px = max(1, math.ceil((width + 2 * pad) * self.scale))
        self.height_px = max(1, math.ceil((height + 2 * pad) * self.scale))
        # Frame coordinates are (x, -y); origin is the frame point of pixel (0, 0).
        self.origin = [x0 - pad, -y1 - pad]
        self.units = units

    def pixels(self, xy):
        xy = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
        return np.column_stack(((xy[:, 0] - self.origin[0]) * self.scale,
                                (-xy[:, 1] - self.origin[1]) * self.scale))

    def box(self, x0, y0, x1, y1):
        """Frame bbox of a source XY extent, at least a few pixels wide."""
        left, right, top, bottom = x0, x1, -y1, -y0
        least = 4 / self.scale
        if right - left < least:
            middle = (left + right) / 2
            left, right = middle - least / 2, middle + least / 2
        if bottom - top < least:
            middle = (top + bottom) / 2
            top, bottom = middle - least / 2, middle + least / 2
        ox, oy = self.origin
        w, h = self.width_px / self.scale, self.height_px / self.scale
        left, top = max(ox, left), max(oy, top)
        right, bottom = min(ox + w, right), min(oy + h, bottom)
        return [round(left, 6), round(top, 6), round(right, 6), round(bottom, 6)]

    def page(self, number, label):
        return {'page': number, 'label': label, 'width': self.width_px / self.scale,
                'height': self.height_px / self.scale, 'origin': self.origin, 'units': self.units,
                'pixel_width': self.width_px, 'pixel_height': self.height_px}

    def canvas(self):
        return np.full((self.height_px, self.width_px, 3), 255, dtype=np.uint8)


def _shift(points):
    # cv2 sub-pixel drawing: 4 fractional bits keeps thin lines faithful.
    return np.round(points * 16).astype(np.int32)


# ---------------------------------------------------------------- DXF

def _dxf(path):
    import ezdxf
    from ezdxf import disassemble, units
    started = time.monotonic()
    document = ezdxf.readfile(str(path))
    code = document.header.get('$INSUNITS', 0)
    try:
        name = units.unit_name(code) if code else None
    except (KeyError, ValueError, TypeError):
        name = None
    label = f'DXF modelspace {name.lower() if name else "units"}, y negated'
    shapes = []  # (handle, kind, [polyline arrays], closed flags, text)
    count = 0
    for entity in document.modelspace():
        if time.monotonic() - started > DXF_TIME_BUDGET:
            raise PreviewUnavailable(f'The DXF plan view exceeded its {DXF_TIME_BUDGET:.0f} s drawing budget')
        handle, kind = entity.dxf.handle, entity.dxftype()
        lines, fills = [], []
        try:
            primitives = list(disassemble.to_primitives(disassemble.recursive_decompose([entity])))
        except Exception:
            continue
        for primitive in primitives:
            if primitive.is_empty:
                continue
            mesh = primitive.mesh
            if mesh is not None:
                vertices = [(v[0], v[1]) for v in mesh.vertices]
                for face in mesh.faces:
                    lines.append(np.array([vertices[i] for i in face] + [vertices[face[0]]], dtype=np.float64))
                continue
            path_ = primitive.path
            if path_ is not None and path_.has_sub_paths:
                parts = [[(v.x, v.y) for v in sub.flattening(primitive.max_flattening_distance)] for sub in path_.sub_paths()]
            else:
                parts = [[(v.x, v.y) for v in primitive.vertices()]]
            for part in parts:
                if part:
                    array = np.array(part, dtype=np.float64)
                    (fills if kind in {'HATCH', 'SOLID', 'TRACE'} and len(part) >= 3 else lines).append(array)
        geometry = lines + fills
        if not geometry:
            continue
        count += sum(len(g) for g in geometry)
        if count > DXF_ENTITY_CAP:
            raise PreviewUnavailable(f'The DXF has more than {DXF_ENTITY_CAP} drawable vertices; the plan view limit was reached')
        text = None
        if kind == 'TEXT' and not entity.dxf.get('rotation', 0):
            text = entity.dxf.text
        shapes.append((handle, kind, lines, fills, text))
    if not shapes:
        raise PreviewUnavailable('The DXF modelspace has no drawable geometry')
    stacked = np.vstack([g for s in shapes for g in s[2] + s[3]])
    finite = np.isfinite(stacked).all(axis=1)
    if not finite.all():
        raise PreviewUnavailable('The DXF has non-finite coordinates')
    x0, y0 = stacked.min(axis=0)
    x1, y1 = stacked.max(axis=0)
    frame = Frame(x0, y0, x1, y1, label)
    image = frame.canvas()
    entities = {}
    # Fills first so outlines stay visible on top.
    for _, _, _, fills, _ in shapes:
        if fills:
            cv2.fillPoly(image, [_shift(frame.pixels(f)) for f in fills], (215, 215, 215), cv2.LINE_AA, 4)
    for handle, kind, lines, fills, text in shapes:
        geometry = lines + fills
        color = (150, 150, 150) if kind in {'TEXT', 'MTEXT', 'HATCH'} else (45, 45, 45)
        polylines = [_shift(frame.pixels(g)) for g in geometry]
        if text and lines:
            # TEXT primitives are box outlines; write the string inside instead.
            box = frame.pixels(lines[0])
            height = box[:, 1].max() - box[:, 1].min()
            width = box[:, 0].max() - box[:, 0].min()
            if height >= 7:
                ascii_text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode() or '?'
                (natural, _), _ = cv2.getTextSize(ascii_text, cv2.FONT_HERSHEY_SIMPLEX, 1, 1)
                # Stay inside the entity's own text box (the cited extent).
                scale = min(height / 22, width / max(1, natural))
                cv2.putText(image, ascii_text, (int(box[:, 0].min()), int(box[:, 1].max())),
                            cv2.FONT_HERSHEY_SIMPLEX, scale, (90, 90, 90), max(1, round(scale)), cv2.LINE_AA)
                polylines = []
        if polylines:
            cv2.polylines(image, polylines, False, color, 1, cv2.LINE_AA, 4)
        points = np.vstack(geometry)
        (gx0, gy0), (gx1, gy1) = points.min(axis=0), points.max(axis=0)
        entities[handle] = [1, *frame.box(gx0, gy0, gx1, gy1)]
    page = frame.page(1, 'Modelspace')
    return [page], {1: image}, entities, {'layout': 'modelspace', 'drawn_entities': len(entities)}


# ---------------------------------------------------------------- IFC

def _storey(element):
    import ifcopenshell.util.element as util
    node, depth = element, 0
    while node is not None and depth < 10:
        if node.is_a('IfcBuildingStorey'):
            return node
        parent = util.get_container(node) or util.get_aggregate(node)
        if parent is None:
            # Doors/windows may sit only in an opening of a contained wall.
            fills = getattr(node, 'FillsVoids', None) or ()
            for rel in fills:
                walls = rel.RelatingOpeningElement.VoidsElements
                if walls:
                    parent = walls[0].RelatingBuildingElement
            # Parts of an aggregate element (curtain-wall plates etc.).
            if parent is None and getattr(node, 'Decomposes', None):
                parent = node.Decomposes[0].RelatingObject
        node, depth = parent, depth + 1
    return None


def _ifc(path):
    import multiprocessing
    import ifcopenshell
    import ifcopenshell.geom
    started = time.monotonic()
    model = ifcopenshell.open(str(path))
    layer_of = {}
    for layer, classes, _, _ in IFC_LAYERS:
        for ifc_class in classes:
            try:
                found = model.by_type(ifc_class)
            except RuntimeError:  # class not in this schema
                continue
            for element in found:
                layer_of[element.id()] = layer
    if not layer_of:
        raise PreviewUnavailable('The IFC has no walls, slabs, spaces, doors or windows to draw')
    if len(layer_of) > IFC_ELEMENT_CAP:
        raise PreviewUnavailable(f'The IFC has {len(layer_of)} plan elements; the plan view limit is {IFC_ELEMENT_CAP}')
    settings = ifcopenshell.geom.settings()
    settings.set('use-world-coords', True)
    elements = [model.by_id(i) for i in layer_of]
    iterator = ifcopenshell.geom.iterator(settings, model, max(1, min(8, multiprocessing.cpu_count())), include=elements)
    shapes = []  # (step id, guid, layer, triangles Nx3x2)
    if iterator.initialize():
        while True:
            if time.monotonic() - started > IFC_TIME_BUDGET:
                raise PreviewUnavailable(f'IFC geometry exceeded the {IFC_TIME_BUDGET:.0f} s plan-view budget '
                                         f'after {len(shapes)} of {len(layer_of)} elements')
            shape = iterator.get()
            verts = np.asarray(shape.geometry.verts, dtype=np.float64).reshape(-1, 3)[:, :2]
            faces = np.asarray(shape.geometry.faces, dtype=np.int64).reshape(-1, 3)
            if len(faces) and np.isfinite(verts).all():
                shapes.append((shape.id, shape.guid, layer_of.get(shape.id), verts[faces]))
            if not iterator.next():
                break
    if not shapes:
        raise PreviewUnavailable('No IFC element has body geometry to draw')
    # Group by storey: one page per storey that has drawable elements.
    groups = {}
    for record in shapes:
        storey = _storey(model.by_id(record[0]))
        groups.setdefault(storey.id() if storey else None, []).append(record)
    storeys = [model.by_id(i) for i in groups if i is not None]
    storeys.sort(key=lambda s: (s.Elevation if isinstance(s.Elevation, (int, float)) else 0, s.id()))
    order = [s.id() for s in storeys] + ([None] if None in groups else [])
    pages, images, entities, page_entities, outside = [], {}, {}, {}, []
    for number, key in enumerate(order, start=1):
        records, dropped = _main_cluster(groups[key])
        outside += [r[1] for r in dropped if r[1]]
        # Each storey gets its own frame (same units and axes) so a small or
        # offset storey still fills the view.
        everything = np.vstack([r[3].reshape(-1, 2) for r in records])
        (x0, y0), (x1, y1) = everything.min(axis=0), everything.max(axis=0)
        frame = Frame(x0, y0, x1, y1, 'IFC world metres (x, -y)')
        if key is None:
            label = 'Elements outside any storey' if storeys else 'Whole model'
        else:
            storey = model.by_id(key)
            label = storey.Name or storey.LongName or f'Storey #{key}'
            if storey.GlobalId:
                page_entities[storey.GlobalId] = number
        image = frame.canvas()
        for layer, _, fill, outline in IFC_LAYERS:
            members = [r for r in records if r[2] == layer]
            if not members:
                continue
            mask = np.zeros(image.shape[:2], dtype=np.uint8)
            polygons = _shift(frame.pixels(np.vstack([r[3] for r in members]).reshape(-1, 2))).reshape(-1, 3, 2)
            # Fill triangles one by one: a single fillPoly call uses the even-odd
            # rule, so stacked faces (top over bottom) would cancel out.
            a, b, c = polygons[:, 0], polygons[:, 1], polygons[:, 2]
            area = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
            for triangle in polygons[area > 0]:  # one projected side; bottoms duplicate tops
                cv2.fillConvexPoly(mask, triangle, 255, cv2.LINE_8, 4)
            # Vertical faces project to slivers; drawing every edge also closes
            # rasterization gaps so outlines follow the silhouette.
            cv2.polylines(mask, list(polygons), True, 255, 1, cv2.LINE_8, 4)
            if fill is not None:
                image[mask > 0] = fill
            contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(image, contours, -1, outline, 1, cv2.LINE_AA)
        for _, guid, _, triangles in records:
            if not guid:
                continue
            flat = triangles.reshape(-1, 2)
            (gx0, gy0), (gx1, gy1) = flat.min(axis=0), flat.max(axis=0)
            entities[guid] = [number, *frame.box(gx0, gy0, gx1, gy1)]
        pages.append(frame.page(number, label))
        images[number] = image
    layout = 'storeys' if storeys else 'whole_model'
    return pages, images, entities, {'layout': layout, 'page_entities': page_entities,
                                     'drawn_entities': len(entities), 'plan_elements': len(layer_of),
                                     'outside_view': outside}


def _main_cluster(records):
    """Keep elements near the building envelope of a storey.

    Exports sometimes park spaces or annotations far from the building; drawing
    them would shrink the plan to a corner. Elements whose extent lies wholly
    outside the envelope (walls, slabs, doors, windows, stairs, widened by 15%)
    are not drawn and get no box; their ids are listed as ``outside_view``.
    """
    envelope = [r for r in records if r[2] in {'wall', 'slab', 'door', 'window', 'stair'}]
    if not envelope:
        return records, []
    points = np.vstack([r[3].reshape(-1, 2) for r in envelope])
    (x0, y0), (x1, y1) = points.min(axis=0), points.max(axis=0)
    pad = 0.15 * max(x1 - x0, y1 - y0, 1e-6)
    kept, dropped = [], []
    for record in records:
        flat = record[3].reshape(-1, 2)
        (a0, b0), (a1, b1) = flat.min(axis=0), flat.max(axis=0)
        inside = a1 >= x0 - pad and a0 <= x1 + pad and b1 >= y0 - pad and b0 <= y1 + pad
        (kept if inside else dropped).append(record)
    return kept, dropped
