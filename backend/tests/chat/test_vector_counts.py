"""Rule-based door/window counts from vector geometry; synthetic PDFs and DXFs, no provider."""
import io
import json

import pytest

from test_chat_api import running
from test_analysis_api import upload, ask

K = 0.5523  # cubic bezier handle length for a quarter circle


def quarter(shape, hinge, radius, start, end):
    """A stroked quarter-circle swing from hinge+start*r to hinge+end*r, plus its straight leaf."""
    import pymupdf
    hx, hy = hinge
    a = pymupdf.Point(hx + start[0] * radius, hy + start[1] * radius)
    b = pymupdf.Point(hx + end[0] * radius, hy + end[1] * radius)
    c1 = a + pymupdf.Point(end[0] * K * radius, end[1] * K * radius)
    c2 = b + pymupdf.Point(start[0] * K * radius, start[1] * K * radius)
    shape.draw_bezier(a, c1, c2, b)
    shape.finish(color=(0, 0, 0), width=.37, closePath=False)
    shape.draw_line(pymupdf.Point(hx, hy), b)
    shape.finish(color=(0, 0, 0), width=.37, closePath=False)


def line(shape, p, q, width=.8):
    import pymupdf
    shape.draw_line(pymupdf.Point(*p), pymupdf.Point(*q))
    shape.finish(color=(0, 0, 0), width=width, closePath=False)


def plan_pdf(doors=True):
    """A3-like sheet: a small plan, a legend strip under a sheet divider, a title scale."""
    import pymupdf
    document = pymupdf.open()
    page = document.new_page(width=842, height=595)
    shape = page.new_shape()
    shape.draw_rect(pymupdf.Rect(20, 20, 822, 575))   # sheet frame
    shape.finish(color=(0, 0, 0), width=1)
    # Plan: a 300 x 200 pt outline made of wall segments, two partitions.
    x0, y0, x1, y1 = 250, 120, 550, 320
    for p, q in [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0)),
                 ((400, y0), (400, y1)), ((x0, 220), (400, 220)), ((400, 260), (x1, 260))]:
        line(shape, p, q)
    for i in range(20):  # wall hatching makes the plan the dominant block
        line(shape, (x0 + 5 + 14 * i, y0), (x0 + 12 + 14 * i, y0 - 6), .3)
    if doors:
        quarter(shape, (300, 220), 25, (1, 0), (0, -1))     # door A in the partition
        quarter(shape, (400, 160), 25, (0, 1), (1, 0))      # door B ...
        quarter(shape, (400, 160), 25, (0, 1), (1, 0))      # ... drawn twice
        quarter(shape, (460, 320), 25, (1, 0), (0, -1))     # double door C: two leaves meeting at x=485
        quarter(shape, (510, 320), 25, (-1, 0), (0, -1))
        # A level marker on a wall: a full circle with one quarter fill and crosshair.
        shape.draw_circle(pymupdf.Point(470, 260), 14)
        shape.finish(color=(0, 0, 0), width=.37, closePath=False)
        quarter(shape, (470, 260), 14, (1, 0), (0, -1))
        line(shape, (470, 260), (484, 260), .37)
    # Sheet divider above the legend strip, and the legend's door sample.
    line(shape, (20, 480), (822, 480), 1)
    quarter(shape, (60, 540), 15, (1, 0), (0, -1))
    shape.commit()
    page.insert_text((90, 535), 'Türe', fontsize=8)
    page.insert_text((600, 540), 'Massstab 1:100', fontsize=8)
    return document.tobytes()


def test_vector_pdf_doors_are_counted_from_swing_arcs_with_page_boxes(tmp_path):
    with running(tmp_path) as base:
        path, drawing = upload(base, 'plan.pdf', plan_pdf())
        answer = ask(base, path, drawing, 'How many doors are there?')
        assert answer['status'] == 'proposal' and answer['review_status'] == 'rule_based'
        assert answer['value'] == 3, answer
        method = answer['calculation']['method']
        assert method['name'] == 'vector_door_swings'
        [note] = method['pages']
        assert (note['duplicates_removed'], note['outside_plan_removed'], note['double_doors'],
                note['circle_symbol_removed'], note['printed_scale']) == (1, 1, 1, 1, '1:100')
        boxes = [e['bbox'] for e in answer['evidence']]
        assert len(boxes) == 3 and all(e['page'] == 1 and e['source_units'] == 'point' for e in answer['evidence'])
        assert all(250 - 1 <= b[0] and b[2] <= 550 + 1 and 120 - 30 <= b[1] and b[3] <= 320 + 1 for b in boxes)
        double = next(e for e in answer['evidence'] if 'double' in e['label'])
        assert double['bbox'] == pytest.approx([460, 295, 510, 320], abs=.6)
        assert 'not from labelled doors' in answer['explanation'] and 'legend' in answer['explanation']
        # German and French questions use the same rule.
        assert ask(base, path, drawing, 'Wie viele Türen gibt es?')['value'] == 3
        assert ask(base, path, drawing, 'Combien de portes y a-t-il ?')['value'] == 3


def test_vector_pdf_without_swing_arcs_falls_through_instead_of_reporting_zero(tmp_path):
    with running(tmp_path) as base:
        path, drawing = upload(base, 'walls.pdf', plan_pdf(doors=False))
        answer = ask(base, path, drawing, 'How many doors are there?')
        # The legend sample is the only arc: no plan geometry answers, so the (unavailable) model is asked.
        assert answer['status'] == 'abstain' and answer['value'] is None
        # A filtered question is not answered by the unfiltered rule.
        path, drawing = upload(base, 'plan.pdf', plan_pdf())
        assert ask(base, path, drawing, 'How many doors are in the kitchen?')['status'] == 'abstain'


def test_vector_pdf_count_fallback_reads_enlarged_plan_region_in_page_points(tmp_path, monkeypatch):
    from stoa.lanes import llm
    payloads = []

    def reply(messages, **kwargs):
        payload = json.loads(messages[1]['content'][0]['text'])
        payloads.append(payload)
        page = payload['pages'][0]
        return json.dumps({'operation': 'count', 'complete': True, 'facts': [
            {'page_ref': page['id'], 'coordinate_space': 'normalized_1000', 'bbox': [480, 480, 520, 520],
             'kind': 'object', 'label': 'chair'}]})
    monkeypatch.setattr(llm, 'chat', reply)
    with running(tmp_path) as base:
        path, drawing = upload(base, 'plan.pdf', plan_pdf())
        answer = ask(base, path, drawing, 'How many chairs are there?')
    processing = answer['image_processing']
    assert processing['method'] == 'enlarged_vector_region'
    x0, y0, x1, y1 = processing['region_bbox']
    assert x0 < 250 and x1 > 550 and y1 < 480       # the plan, not the legend strip or the whole sheet
    assert processing['scale'] > 2 * 1600 / 842      # far more pixels per point than the sheet preview
    assert all(p['facts'] == [] for p in payloads)  # page text facts are not offered per region
    assert answer['value'] >= 1
    for e in answer['evidence']:
        assert e['page'] == 1 and x0 <= e['bbox'][0] < e['bbox'][2] <= x1 and y0 <= e['bbox'][1] < e['bbox'][3] <= y1


def test_visual_zero_says_nothing_was_detected_and_is_unverified(tmp_path, monkeypatch):
    import cv2
    import numpy as np
    from stoa.lanes import llm
    monkeypatch.setattr(llm, 'chat', lambda messages, **k: json.dumps(
        {'operation': 'count', 'complete': True, 'facts': []}))
    image = np.full((300, 400, 3), 255, np.uint8)
    cv2.rectangle(image, (50, 50), (350, 250), (0, 0, 0), 3)
    with running(tmp_path) as base:
        path, drawing = upload(base, 'plan.png', cv2.imencode('.png', image)[1].tobytes())
        answer = ask(base, path, drawing, 'How many saunas are there?')
    assert answer['status'] == 'proposal' and answer['value'] == 0
    assert 'detected none' in answer['explanation'] and 'unverified' in answer['explanation']
    assert answer['evidence'][0]['coverage']


def opening_dxf(loose=False):
    import ezdxf
    document = ezdxf.new()
    document.header['$INSUNITS'] = 6  # metres
    space = document.modelspace()
    for layer in ('A-DOOR', 'FENSTER', 'WALL'):
        document.layers.add(layer)
    space.add_lwpolyline([(0, 0), (10, 0), (10, 6), (0, 6)], close=True, dxfattribs={'layer': 'WALL'})

    def door(hinge, start, end):
        x, y = hinge
        space.add_arc((x, y), .9, start, end, dxfattribs={'layer': 'A-DOOR'})
        space.add_lwpolyline([(x, y), (x + .05, y), (x + .05, y + .9), (x, y + .9), (x, y)], dxfattribs={'layer': 'A-DOOR'})
    door((2, 0), 0, 90)
    door((2, 0), 0, 90)            # the same door exported twice
    door((5, 3), 90, 180)
    door((7, 0), 0, 90)            # double door: leaves meet at x = 7.9
    door((8.8, 0), 90, 180)
    for x in (1, 4):               # windows: frame outline with two glazing lines inside
        space.add_lwpolyline([(x, 5.85), (x + 1.2, 5.85), (x + 1.2, 6.15), (x, 6.15)], close=True, dxfattribs={'layer': 'FENSTER'})
        space.add_line((x, 5.95), (x + 1.2, 5.95), dxfattribs={'layer': 'FENSTER'})
        space.add_line((x, 6.05), (x + 1.2, 6.05), dxfattribs={'layer': 'FENSTER'})
    if loose:
        space.add_line((0, 3), (0, 4), dxfattribs={'layer': 'A-DOOR'})  # a sliding door without a swing
    stream = io.StringIO()
    document.write(stream)
    return stream.getvalue().encode()


def test_dxf_door_and_window_layers_are_counted_with_entity_boxes(tmp_path):
    with running(tmp_path) as base:
        path, drawing = upload(base, 'plan.dxf', opening_dxf())
        doors = ask(base, path, drawing, 'How many doors are there?')
        assert (doors['status'], doors['review_status'], doors['value']) == ('proposal', 'rule_based', 3), doors
        assert doors['calculation']['method']['name'] == 'dxf_layer_doors'
        assert doors['calculation']['method']['layers'] == ['A-DOOR']
        assert all(e['native_type'] == 'ARC' and e['page'] == 1 and e['bbox'] for e in doors['evidence'])
        assert sum('double door' in e['label'] for e in doors['evidence']) == 1
        windows = ask(base, path, drawing, 'Wie viele Fenster gibt es?')
        assert (windows['value'], windows['calculation']['method']['layers']) == (2, ['FENSTER'])
        assert all(e['native_type'] == 'LWPOLYLINE' and e['bbox'] for e in windows['evidence'])


def test_ambiguous_dxf_door_layer_keeps_the_existing_path(tmp_path):
    with running(tmp_path) as base:
        path, drawing = upload(base, 'plan.dxf', opening_dxf(loose=True))
        answer = ask(base, path, drawing, 'How many doors are there?')
        assert answer['status'] == 'abstain'          # the controlled provider is unavailable
        assert ask(base, path, drawing, 'How many windows are there?')['value'] == 2


def test_count_questions_in_the_five_languages():
    from stoa_chat.analysis import question_kind
    for question in ['How many doors are there?', 'Wie viele Fenster gibt es?', 'Combien de portes y a-t-il ?',
                     'Quante finestre ci sono?', 'Kuinka monta ovea on?']:
        assert question_kind(question) == 'count', question
