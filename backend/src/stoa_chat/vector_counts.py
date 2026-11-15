"""Rule-based door and window counts from vector geometry (PDF paths, DXF layers).

These are inferences from drawing conventions, not labelled inventories: a door is a
quarter-circle swing arc with a leaf from its hinge, a DXF window is a closed outline on a
layer whose name means window. Every counted object is cited; when the geometry does not
answer the question (no arcs, a scanned page, ambiguous layer content) the caller falls
through to the visual path instead of reporting zero.
"""
import math
import re


# Physical swing radius of a hinged door leaf; generous so narrow and wide doors both pass.
DOOR_RADIUS_M = (.35, 3.)
# Without a printed scale, radii must stay within this factor band of the median arc, and on paper
# a door leaf drawn at a usual plan scale (about 1:20 to 1:200) spans 8 to 120 points.
RELATIVE_RADIUS = (.5, 2.)
PAPER_RADIUS_PT = (8., 120.)
ARC_TOLERANCE = .06          # max radial deviation, as a fraction of the radius
LEAF_TOLERANCE = .2          # leaf endpoints within this fraction of the radius
CLUSTER_GAP = .015           # drawing elements this close (fraction of the sheet side) connect
MAIN_CLUSTER_SHARE = .1      # smaller blocks (stray symbols, notes) are not plan drawing
MAX_IMAGE_SHARE = .1         # a page whose raster images cover more than this is not pure vector
MAX_PATHS = 20000            # larger CAD sheets fall through to the visual path (bounded latency)

DOOR_LAYER = re.compile(r'(?<![a-z])(doors?|t(?:ü|ue|u)r(?:e|en)?|portes?|porta|puertas?|deur(?:en)?|ovi|ovet)(?![a-z])')
WINDOW_LAYER = re.compile(r'(?<![a-z])(windows?|fenster|fen(?:ê|e)tres?|finestr[ae]|ventanas?|ikkuna(?:t)?|vensters?)(?![a-z])')


def method_answer(value, evidence, facts, target, method, explanation):
    """The proposal shape of the extraction path, with the counting rule made explicit."""
    return {'status': 'proposal', 'value': value, 'unit': 'count', 'evidence': evidence,
            'review_status': 'rule_based', 'target': target, 'explanation': explanation,
            'calculation': {'operation': 'count', 'count_basis': 'objects', 'method': method, 'facts': facts}}


# ---------------------------------------------------------------- shared arc geometry

def quarter_arc(points, tolerance=ARC_TOLERANCE):
    """(centre, radius, start, end) when the points trace about a quarter circle, else None.

    A 90-degree arc from A to B has its centre on the perpendicular bisector of AB, half a
    chord away; both candidates are tried and every sample must lie on the circle."""
    (ax, ay), (bx, by) = points[0], points[-1]
    chord = math.hypot(bx - ax, by - ay)
    if chord <= 0:
        return None
    radius = chord / math.sqrt(2)
    mx, my = (ax + bx) / 2, (ay + by) / 2
    nx, ny = -(by - ay) / chord, (bx - ax) / chord
    for sign in (1, -1):
        cx, cy = mx + sign * nx * chord / 2, my + sign * ny * chord / 2
        if all(abs(math.hypot(x - cx, y - cy) - radius) <= tolerance * radius for x, y in points):
            # Samples must stay inside the 90-degree sector between A and B (not the 270 one).
            start = math.atan2(ay - cy, ax - cx)
            spans = [(math.atan2(y - cy, x - cx) - start) % (2 * math.pi) for x, y in points]
            sweep = (math.atan2(by - cy, bx - cx) - start) % (2 * math.pi)
            if sweep > math.pi:
                spans = [(2 * math.pi - s) % (2 * math.pi) for s in spans]
            if max(spans) <= math.radians(100):
                return (cx, cy), radius, (ax, ay), (bx, by)
    return None


def union(rects):
    """Bounding box of rects, lines included (PyMuPDF's own union skips zero-width rects)."""
    import pymupdf
    rects = list(rects)
    if not rects:
        return None
    return pymupdf.Rect(min(r.x0 for r in rects), min(r.y0 for r in rects),
                        max(r.x1 for r in rects), max(r.y1 for r in rects))


def near(p, q, distance):
    return math.hypot(p[0] - q[0], p[1] - q[1]) <= distance


def dedupe(arcs):
    """Coincident arcs (the same swing drawn twice) count once."""
    kept = []
    for arc in arcs:
        (c, r, a, b) = arc['geometry']
        tol = .05 * r
        if not any(abs(r - k['geometry'][1]) <= tol and near(c, k['geometry'][0], tol)
                   and {near(a, k['geometry'][2], tol) or near(a, k['geometry'][3], tol),
                        near(b, k['geometry'][2], tol) or near(b, k['geometry'][3], tol)} == {True}
                   for k in kept):
            kept.append(arc)
    return kept


def circle_parts(arcs, circles):
    """Arcs lying on a full circle drawn at the same place are pieces of a round symbol (a level
    or section marker with quarter fills), not door swings."""
    parts = []
    for arc in arcs:
        (c, r, *_), tol = arc['geometry'], .08 * arc['geometry'][1]
        if any(abs(cr - r) <= tol and near(cc, c, tol) for cc, cr in circles):
            parts.append(arc)
    return parts


def _circles(drawings):
    """(centre, radius) of closed, square curve paths: full circles."""
    out = []
    for d in drawings:
        items = d['items']
        if not items or any(i[0] != 'c' for i in items):
            continue
        first, last = items[0][1], items[-1][4]
        r = d['rect']
        if abs(first.x - last.x) + abs(first.y - last.y) <= .02 * max(r.width, r.height, 1e-9) and abs(r.width - r.height) <= .05 * max(r.width, r.height):
            out.append((((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2), r.width / 2))
    return out


def _meeting(a, b):
    """Two equal arcs whose tips meet at the midpoint of their hinges: the two leaves of one
    opening (they may swing to the same or to opposite sides)."""
    (ca, ra, *ends_a), (cb, rb, *ends_b) = a['geometry'], b['geometry']
    tol = .08 * max(ra, rb)
    mid = ((ca[0] + cb[0]) / 2, (ca[1] + cb[1]) / 2)
    return (abs(ra - rb) <= tol and abs(math.hypot(ca[0] - cb[0], ca[1] - cb[1]) - ra - rb) <= 2 * tol
            and any(near(p, mid, tol) for p in ends_a) and any(near(p, mid, tol) for p in ends_b))


def pair_double_doors(arcs):
    """Group arcs into doors: two equal leaves meeting at the middle of one opening are one door."""
    doors, used = [], set()
    for i, a in enumerate(arcs):
        if i in used:
            continue
        group = [a]
        for j in range(i + 1, len(arcs)):
            if j not in used and _meeting(a, arcs[j]):
                group.append(arcs[j])
                used.add(j)
                break
        used.add(i)
        doors.append(group)
    return doors


def plausible(arcs, metres_per_unit):
    """Keep arcs with a door-sized radius: physical when the scale is known, else relative."""
    if not arcs:
        return []
    if metres_per_unit:
        low, high = DOOR_RADIUS_M
        return [a for a in arcs if low <= a['geometry'][1] * metres_per_unit <= high]
    radii = sorted(a['geometry'][1] for a in arcs)
    median = radii[len(radii) // 2]
    return [a for a in arcs if RELATIVE_RADIUS[0] * median <= a['geometry'][1] <= RELATIVE_RADIUS[1] * median]


# ---------------------------------------------------------------- PDF pages

def _segments(drawings):
    """Straight segments of every path (lines, rectangle and quad edges) as (x0, y0, x1, y1)."""
    out = []
    for d in drawings:
        for item in d['items']:
            if item[0] == 'l':
                out.append((item[1].x, item[1].y, item[2].x, item[2].y))
            elif item[0] in {'re', 'qu'}:
                q = item[1].quad if item[0] == 're' else item[1]
                corners = [q.ul, q.ur, q.lr, q.ll]
                out += [(p.x, p.y, n.x, n.y) for p, n in zip(corners, corners[1:] + corners[:1])]
    return out


def _bezier(p0, p1, p2, p3, steps=8):
    return [((1 - t) ** 3 * p0.x + 3 * (1 - t) ** 2 * t * p1.x + 3 * (1 - t) * t * t * p2.x + t ** 3 * p3.x,
             (1 - t) ** 3 * p0.y + 3 * (1 - t) ** 2 * t * p1.y + 3 * (1 - t) * t * t * p2.y + t ** 3 * p3.y)
            for t in (i / steps for i in range(steps + 1))]


def _path_chains(d):
    """Sampled point chains of a stroked, unfilled path: each continuous run of curves, or of at
    least six short lines (an arc flattened to a polyline). A swing and its leaf may share a path."""
    items = d['items']
    if not items or d.get('fill') is not None or 's' not in d.get('type', ''):
        return []
    runs, run = [], []
    for item in items:
        if item[0] not in {'c', 'l'}:
            runs.append(run); run = []
            continue
        start, end = item[1], item[-1]
        if run and (run[-1][0] != item[0] or abs(run[-1][-1].x - start.x) + abs(run[-1][-1].y - start.y) > 1e-3):
            runs.append(run); run = []
        run.append(item)
    runs.append(run)
    # A flattened arc is many short equal lines; a long line in the same run (often the leaf,
    # drawn hinge -> tip before the arc) ends the arc chain.
    split = []
    for run in runs:
        if run and run[0][0] == 'l' and len(run) >= 6:
            lengths = [math.hypot(i[2].x - i[1].x, i[2].y - i[1].y) for i in run]
            typical = sorted(lengths)[len(lengths) // 2]
            part = []
            for item, length in zip(run, lengths):
                if length > 4 * typical:
                    split.append(part); part = []
                else:
                    part.append(item)
            split.append(part)
        else:
            split.append(run)
    chains = []
    for run in split:
        if not run or (run[0][0] == 'l' and len(run) < 6):
            continue
        if run[0][0] == 'c':
            points = []
            for item in run:
                sampled = _bezier(*item[1:5])
                points += sampled if not points else sampled[1:]
        else:
            points = [(run[0][1].x, run[0][1].y)] + [(i[2].x, i[2].y) for i in run]
        chains.append(points)
    return chains


def _has_leaf(arc, segments):
    """A swing has a straight leaf from its hinge (the centre) to one end of the arc."""
    import numpy as np
    (c, r, a, b) = arc
    if not len(segments):
        return False
    tol = LEAF_TOLERANCE * r
    s = np.asarray(segments, dtype=float)
    def close(x, y, p):
        return np.hypot(x - p[0], y - p[1]) <= tol
    for start, end in ((s[:, :2], s[:, 2:]), (s[:, 2:], s[:, :2])):
        hinge = close(start[:, 0], start[:, 1], c)
        tip = close(end[:, 0], end[:, 1], a) | close(end[:, 0], end[:, 1], b)
        if (hinge & tip).any():
            return True
    return False


def _clusters(drawings, page_rect):
    """Group drawing elements that touch (within a small gap) into blocks; return a block id
    per drawing (None for sheet furniture: frames and lines spanning most of the sheet)."""
    from shapely import STRtree, box
    width, height = page_rect.width, page_rect.height
    gap = CLUSTER_GAP * max(width, height) / 2
    nodes = []
    for index, d in enumerate(drawings):
        r = d['rect']
        if r.width > .5 * width or r.height > .5 * height:
            continue
        nodes.append(index)
    geometries = [box(drawings[i]['rect'].x0 - gap, drawings[i]['rect'].y0 - gap,
                      drawings[i]['rect'].x1 + gap, drawings[i]['rect'].y1 + gap) for i in nodes]
    parent = list(range(len(nodes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    if geometries:
        tree = STRtree(geometries)
        left, right = tree.query(geometries, predicate='intersects')
        for i, j in zip(left.tolist(), right.tolist()):
            a, b = find(i), find(j)
            if a != b:
                parent[a] = b
    block = [None] * len(drawings)
    for position, index in enumerate(nodes):
        block[index] = find(position)
    return block


def visible_drawings(page):
    """Stroked and filled paths with their rect cut to the active clip region.

    Hatch patterns are drawn as large tiles clipped to a wall; their raw rects reach far past
    the drawing and would join the plan to the legend and title block."""
    import pymupdf
    stack, out = [], []
    for d in page.get_drawings(extended=True):
        level = d.get('level', 0)
        while stack and stack[-1][0] >= level:
            stack.pop()
        if d['type'] == 'clip':
            stack.append((level, pymupdf.Rect(d['scissor'])))
            continue
        if d['type'] == 'group' or 'items' not in d:
            continue
        rect = pymupdf.Rect(d['rect'])
        for _, scissor in stack:
            # Manual intersection: PyMuPDF treats a line's zero-width rect as empty.
            rect = pymupdf.Rect(max(rect.x0, scissor.x0), max(rect.y0, scissor.y0),
                                min(rect.x1, scissor.x1), min(rect.y1, scissor.y1))
        if rect.x0 > rect.x1 or rect.y0 > rect.y1:
            continue   # wholly clipped away
        out.append({**d, 'rect': rect})
    return out


def mostly_vector(page):
    import pymupdf
    area = page.rect.width * page.rect.height
    try:
        covered = sum(abs(pymupdf.Rect(i['bbox']) & page.rect) for i in page.get_image_info())
    except (RuntimeError, ValueError):
        return False
    return covered <= MAX_IMAGE_SHARE * area


def plan_blocks(page, drawings, segments):
    """(block per drawing, block sizes, main block size, main block extent, sheet dividers)."""
    import pymupdf
    from shapely.geometry import LineString
    block = _clusters(drawings, page.rect)
    sizes = {}
    for b in block:
        if b is not None:
            sizes[b] = sizes.get(b, 0) + 1
    if not sizes:
        return None
    main_block, main = max(sizes.items(), key=lambda item: item[1])
    extent = union(drawings[index]['rect'] for index, b in enumerate(block) if b == main_block)
    # Sheet dividers (e.g. the line above a legend and title strip) are long straight lines that
    # reach beyond the main plan block; whatever lies on their far side is not part of the plan.
    reach = .5 * min(page.rect.width, page.rect.height)
    margin = CLUSTER_GAP * max(page.rect.width, page.rect.height)
    grown = pymupdf.Rect(extent.x0 - margin, extent.y0 - margin, extent.x1 + margin, extent.y1 + margin)
    import numpy as np
    segments = np.asarray(segments, dtype=float).reshape(-1, 4)
    long = segments[np.hypot(segments[:, 2] - segments[:, 0], segments[:, 3] - segments[:, 1]) > reach]
    dividers = [LineString([(x0, y0), (x1, y1)]) for x0, y0, x1, y1 in long.tolist()
                if not grown.contains(pymupdf.Point(x0, y0)) and not grown.contains(pymupdf.Point(x1, y1))]
    return block, sizes, main, extent, dividers


def content_region(page):
    """The page region holding the plan (all plan-sized blocks of vector paths), padded; None
    when the page is not mostly vector or the plan already fills most of the sheet."""
    import pymupdf
    if not mostly_vector(page):
        return None
    drawings = visible_drawings(page)
    if not 20 <= len(drawings) <= MAX_PATHS:
        return None
    blocks = plan_blocks(page, drawings, _segments(drawings))
    if blocks is None:
        return None
    block, sizes, main, extent, dividers = blocks
    from shapely.geometry import LineString
    centre = ((extent.x0 + extent.x1) / 2, (extent.y0 + extent.y1) / 2)
    kept = []
    for d, b in zip(drawings, block):
        if b is None or sizes[b] < MAIN_CLUSTER_SHARE * main:
            continue
        r = d['rect']
        middle = ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
        if any(LineString([middle, centre]).intersects(x) for x in dividers):
            continue
        kept.append(r)
    # The region must hold most of the drawing and be a real part of the sheet, not a stray symbol.
    if len(kept) < .4 * sum(sizes.values()):
        return None
    region = union(kept)
    pad = .02 * max(page.rect.width, page.rect.height)
    region = pymupdf.Rect(region.x0 - pad, region.y0 - pad, region.x1 + pad, region.y1 + pad) & page.rect
    if region.is_empty or not .03 * abs(page.rect) <= abs(region) <= .6 * abs(page.rect):
        return None
    return region


def page_doors(page):
    """Door swings on one vector PDF page, or None when the page geometry cannot answer.

    Returns (doors, notes): each door is a list of one or two arc records with page-space boxes."""
    import pymupdf
    if not mostly_vector(page):
        return None
    drawings = visible_drawings(page)
    if not drawings or len(drawings) > MAX_PATHS:
        return None
    candidates = []
    for index, d in enumerate(drawings):
        for points in _path_chains(d):
            geometry = quarter_arc(points)
            if geometry:
                xs, ys = [p[0] for p in points], [p[1] for p in points]
                candidates.append({'index': index, 'geometry': geometry,
                                   'rect': pymupdf.Rect(min(xs), min(ys), max(xs), max(ys))})
    if not candidates:
        return None
    import numpy as np
    segments = np.asarray(_segments(drawings), dtype=float).reshape(-1, 4)
    candidates = [a for a in candidates if _has_leaf(a['geometry'], segments)]
    if not candidates:
        return None
    # Legend and title-block samples sit apart from the plan: keep arcs only in plan-sized blocks.
    blocks = plan_blocks(page, drawings, segments)
    if blocks is None:
        return None
    block, sizes, main, extent, dividers = blocks
    from shapely.geometry import LineString
    centre = ((extent.x0 + extent.x1) / 2, (extent.y0 + extent.y1) / 2)

    def across(arc):
        line = LineString([arc['geometry'][0], centre])
        return any(line.intersects(d) for d in dividers)
    excluded = [a for a in candidates if block[a['index']] is None or sizes[block[a['index']]] < MAIN_CLUSTER_SHARE * main
                or across(a)]
    inside = [a for a in candidates if a not in excluded]
    scale = printed_scale(page)
    metres_per_point = .0254 / 72 * scale if scale else None
    on_paper = inside if metres_per_point else [a for a in inside if PAPER_RADIUS_PT[0] <= a['geometry'][1] <= PAPER_RADIUS_PT[1]]
    sized = plausible(on_paper, metres_per_point)
    symbols = circle_parts(sized, _circles(drawings))
    sized = [a for a in sized if a not in symbols]
    if not sized:
        return None
    unique = dedupe(sized)
    doors = pair_double_doors(unique)
    return doors, {'arcs_found': len(candidates), 'duplicates_removed': len(sized) - len(unique),
                   'outside_plan_removed': len(excluded), 'size_removed': len(inside) - len(sized) - len(symbols),
                   'circle_symbol_removed': len(symbols),
                   'double_doors': sum(len(d) == 2 for d in doors),
                   'printed_scale': f'1:{scale}' if scale else None}


def printed_scale(page):
    """The one drawing scale printed on the page (1:N), or None when absent or ambiguous."""
    found = {int(n) for n in re.findall(r'(?<![\d.,:])1\s*:\s*(\d{1,4})(?![\d.,])', page.get_text())}
    found = {n for n in found if 5 <= n <= 5000}
    return next(iter(found)) if len(found) == 1 else None


def pdf_door_answer(drawing):
    """Count door swings on every page of a vector PDF; None when any page cannot answer."""
    import pymupdf
    from .native import page_evidence
    evidence, facts, notes = [], [], []
    with pymupdf.open(drawing['path']) as doc:
        if len(doc) > 12:
            return None
        for number, page in enumerate(doc):
            found = page_doors(page)
            if found is None:
                return None
            doors, note = found
            notes.append({'page': number + 1, **note})
            for door in doors:
                rect = union(arc['rect'] for arc in door) * page.rotation_matrix
                box = [max(0, rect.x0), max(0, rect.y0), min(page.rect.width, rect.x1), min(page.rect.height, rect.y1)]
                if box[0] >= box[2] or box[1] >= box[3]:
                    return None
                label = 'double door (two swing arcs)' if len(door) == 2 else 'door swing arc'
                ev = page_evidence(drawing, number + 1, box) | {'label': label}
                evidence.append(ev)
                facts.append({'kind': 'object', 'label': label, 'value': 1,
                              'radius_points': [round(a['geometry'][1], 2) for a in door]})
    method = {'name': 'vector_door_swings', 'rule': 'quarter-circle stroked arc with a straight leaf from its hinge, '
              'door-sized radius, inside the main plan block; coincident arcs counted once, two leaves meeting '
              'mid-opening counted as one door', 'pages': notes}
    left = [f'{n} {text}' for n, text in ((sum(x['duplicates_removed'] for x in notes), 'duplicate arc(s)'),
                                           (sum(x['outside_plan_removed'] for x in notes), 'arc(s) outside the plan such as a legend sample'),
                                           (sum(x['size_removed'] for x in notes), 'arc(s) not door-sized'),
                                           (sum(x['circle_symbol_removed'] for x in notes), 'arc(s) of round symbols')) if n]
    explanation = (f'Counted {len(evidence)} door(s) from their swing arcs in the PDF geometry by a drawing rule, '
                   f'not from labelled doors{", leaving out " + ", ".join(left) if left else ""}; '
                   'doors drawn without a swing arc, such as sliding doors, are not included.')
    return method_answer(len(evidence), evidence, facts, 'door', method, explanation)


# ---------------------------------------------------------------- DXF layers

def _layer_kind(name):
    name = name.casefold()
    door, window = bool(DOOR_LAYER.search(name)), bool(WINDOW_LAYER.search(name))
    return 'door' if door and not window else 'window' if window and not door else None


def _extent(entity):
    from ezdxf import bbox
    box = bbox.extents([entity], fast=True)
    return (box.extmin.x, box.extmin.y, box.extmax.x, box.extmax.y) if box.has_data else None


def _touches(a, b, tol):
    return a[0] - tol <= b[2] and b[0] - tol <= a[2] and a[1] - tol <= b[3] and b[1] - tol <= a[3]


def dxf_opening_answer(drawing, target):
    """Count doors or windows on layers whose names mean door/window; None when ambiguous."""
    import ezdxf
    from ezdxf import units
    document = ezdxf.readfile(drawing['path'])
    entities = [e for e in document.modelspace() if _layer_kind(e.dxf.layer) == target]
    if not entities:
        return None
    code = document.header.get('$INSUNITS', 0)
    try:
        metres = units.conversion_factor(code, units.M) if code else None
    except (ValueError, TypeError):
        metres = None
    inserts = [e for e in entities if e.dxftype() == 'INSERT']
    layers = sorted({e.dxf.layer for e in entities})
    if inserts:
        # Block references: one reference is one placed object. Mixed loose geometry is ambiguous.
        if len(inserts) != len(entities):
            return None
        seen, groups = set(), []
        for e in inserts:
            key = (e.dxf.name, round(e.dxf.insert.x, 3), round(e.dxf.insert.y, 3))
            if key not in seen:
                seen.add(key)
                groups.append([e])
        rule = f'one block reference per {target} on layer(s) named for {target}s; identical references counted once'
    elif target == 'door':
        arcs, others = [], []
        for e in entities:
            if e.dxftype() == 'ARC':
                sweep = (e.dxf.end_angle - e.dxf.start_angle) % 360
                if 75 <= sweep <= 105:
                    c, r = (e.dxf.center.x, e.dxf.center.y), e.dxf.radius
                    a, b = e.start_point, e.end_point
                    arcs.append({'entity': e, 'geometry': (c, r, (a.x, a.y), (b.x, b.y))})
                    continue
            others.append(e)
        arcs = plausible(arcs, metres)
        if not arcs:
            return None
        # Leaves and jambs must belong to a swing; loose geometry (e.g. sliding doors) is ambiguous.
        boxes = [_extent(a['entity']) for a in arcs]
        tol = .1 * min(a['geometry'][1] for a in arcs)
        for e in others:
            box = _extent(e)
            if box is None or not any(b and _touches(box, b, tol) for b in boxes):
                return None
        unique = dedupe(arcs)
        groups = [[a['entity'] for a in door] for door in pair_double_doors(unique)]
        rule = ('one door per quarter-circle swing arc on layer(s) named for doors; coincident arcs counted once, '
                'two leaves meeting mid-opening counted as one door')
    else:
        outlines, others = [], []
        for e in entities:
            points = None
            if e.dxftype() == 'LWPOLYLINE':
                points = [(p[0], p[1]) for p in e.get_points()]
                closed = e.closed or (len(points) > 3 and near(points[0], points[-1], 1e-9))
                if closed and len(points) >= 4 and not any(p[4] for p in e.get_points()):
                    outlines.append((e, points))
                    continue
            others.append(e)
        if not outlines:
            return None
        boxes = [(min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)) for _, pts in outlines]
        sizes = sorted(max(b[2] - b[0], b[3] - b[1]) for b in boxes)
        tol = .02 * sizes[len(sizes) // 2]
        # Glazing lines must lie inside an outline; anything else makes the layer ambiguous.
        for e in others:
            box = _extent(e)
            if box is None or not any(b[0] - tol <= box[0] and box[2] <= b[2] + tol and b[1] - tol <= box[1] and box[3] <= b[3] + tol for b in boxes):
                return None
        seen, groups = set(), []
        for (e, pts), b in zip(outlines, boxes):
            key = tuple(round(v, 3) for v in b)
            if key not in seen:
                seen.add(key)
                groups.append([e])
        rule = 'one window per closed outline on layer(s) named for windows; glazing lines inside it belong to it; identical outlines counted once'
    evidence, facts = [], []
    for group in groups:
        first = group[0]
        label = f'{target} on layer {first.dxf.layer}' + (' (double door, two leaves)' if len(group) == 2 else '')
        evidence.append({'drawing_id': drawing['id'], 'entity_id': first.dxf.handle, 'entity_handle': first.dxf.handle,
                         'native_type': first.dxftype(), 'label': label,
                         'details': {'layer': first.dxf.layer, 'handles': [e.dxf.handle for e in group]}})
        facts.append({'kind': 'object', 'label': label, 'value': 1, 'handles': [e.dxf.handle for e in group]})
    if not evidence:
        return None
    method = {'name': 'dxf_layer_' + target + 's', 'layers': layers, 'rule': rule,
              'entities_on_layers': len(entities)}
    explanation = (f'Counted {len(evidence)} {target}(s) from DXF entities on layer(s) {", ".join(layers)} by a layer-name '
                   f'and geometry rule, not from labelled {target} objects, with identical copies counted once.')
    return method_answer(len(evidence), evidence, facts, target, method, explanation)


def opening_count(drawing, target):
    if drawing['format'] == 'dxf' and target in {'door', 'window'}:
        return dxf_opening_answer(drawing, target)
    if drawing['format'] == 'pdf' and target == 'door':
        return pdf_door_answer(drawing)
    return None
