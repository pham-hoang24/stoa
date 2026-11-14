"""Plan-view previews for IFC/DXF uploads: geometry-derived pages and evidence boxes."""
import io
import threading
import time

import cv2
import numpy as np
import pytest

from test_chat_api import running, request
from test_analysis_api import upload, ask


def dxf_bytes():
    import ezdxf
    document = ezdxf.new()
    document.header['$INSUNITS'] = 6  # metres
    space = document.modelspace()
    space.add_line((0, 0), (10, 0))
    space.add_line((0, 0), (0, 4))
    space.add_circle((20, 5), 2)
    block = document.blocks.new('MARK')
    block.add_line((0, 0), (1, 1))
    space.add_blockref('MARK', (5, 2))
    space.add_text('Room', dxfattribs={'height': 0.5, 'insert': (2, 1)})
    stream = io.StringIO()
    document.write(stream)
    return stream.getvalue().encode()


def ifc_bytes():
    """Two storeys: a wall below, a door with geometry and one without above."""
    import ifcopenshell
    import ifcopenshell.api as api
    model = ifcopenshell.file(schema='IFC4')
    project = api.run('root.create_entity', model, ifc_class='IfcProject', name='Plan test')
    api.run('unit.assign_unit', model)
    context = api.run('context.add_context', model, context_type='Model')
    body = api.run('context.add_context', model, context_type='Model', context_identifier='Body',
                   target_view='MODEL_VIEW', parent=context)
    site = api.run('root.create_entity', model, ifc_class='IfcSite', name='Site')
    building = api.run('root.create_entity', model, ifc_class='IfcBuilding', name='Building')
    api.run('aggregate.assign_object', model, relating_object=project, products=[site])
    api.run('aggregate.assign_object', model, relating_object=site, products=[building])
    storeys = []
    for index, name in enumerate(['Ground', 'Upper']):
        storey = api.run('root.create_entity', model, ifc_class='IfcBuildingStorey', name=name)
        storey.Elevation = 3.0 * index
        api.run('aggregate.assign_object', model, relating_object=building, products=[storey])
        storeys.append(storey)

    def solid(ifc_class, storey, x, y, length, thickness, height):
        element = api.run('root.create_entity', model, ifc_class=ifc_class, name=ifc_class)
        matrix = np.eye(4)
        matrix[0, 3], matrix[1, 3] = x, y
        api.run('geometry.edit_object_placement', model, product=element, matrix=matrix)
        shape = api.run('geometry.add_wall_representation', model, context=body, length=length,
                        height=height, thickness=thickness)
        api.run('geometry.assign_representation', model, product=element, representation=shape)
        api.run('spatial.assign_container', model, relating_structure=storey, products=[element])
        return element

    wall = solid('IfcWall', storeys[0], 0, 0, 10, 0.3, 3)
    door = solid('IfcDoor', storeys[1], 2, 5, 1, 0.1, 2)
    bare = api.run('root.create_entity', model, ifc_class='IfcDoor', name='No geometry')
    api.run('spatial.assign_container', model, relating_structure=storeys[1], products=[bare])
    ids = {'wall': wall.GlobalId, 'door': door.GlobalId, 'bare': bare.GlobalId,
           'ground': storeys[0].GlobalId, 'upper': storeys[1].GlobalId}
    return model.to_string().encode(), ids


def plan(base, drawing):
    path = drawing['asset_url'].removeprefix('/api').replace('/assets/', '/previews/')
    for _ in range(600):
        status, result = request(base, path)
        if result['status'] != 'pending':
            assert status == 200
            return path, result
        assert status == 202
        time.sleep(0.05)
    pytest.fail('plan view never finished')


def image(raw):
    return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)


def pixel(page, x, y):
    """Source XY → preview pixel through the page descriptor (frame is (x, -y))."""
    sx, sy = page['pixel_width'] / page['width'], page['pixel_height'] / page['height']
    return round((x - page['origin'][0]) * sx), round((-y - page['origin'][1]) * sy)


def test_dxf_upload_gets_a_modelspace_plan_with_entity_boxes_on_it(tmp_path):
    with running(tmp_path) as base:
        path, drawing = upload(base, 'plan.dxf', dxf_bytes())
        assert drawing['pages'] == []  # raster page scope (and model extraction) unchanged
        preview, result = plan(base, drawing)
        assert result['status'] == 'ready' and result['layout'] == 'modelspace'
        [page] = result['pages']
        assert page['units'] == 'DXF modelspace meters, y negated'
        status, raw = request(base, preview + '/1')
        assert status == 200 and raw.startswith(b'\x89PNG')
        picture = image(raw)
        assert picture.shape[:2] == (page['pixel_height'], page['pixel_width'])
        # The 10 m line is drawn where the frame says it is.
        x, y = pixel(page, 5, 0)
        assert picture[y - 1:y + 2, x].min() < 128
        assert picture[pixel(page, 15, 1)[::-1]].min() == 255  # empty modelspace stays white
        answer = ask(base, path, drawing, 'How many lines are there?')
        assert answer['value'] == 2 and len(answer['evidence']) == 2
        for evidence in answer['evidence']:
            assert evidence['page'] == 1
            assert evidence['bbox'] == result['entities'][evidence['entity_id']][1:]
            assert evidence['preview_url'].endswith('/previews/' + drawing['id'] + '/1')
            assert evidence['source_width'] == page['width'] and evidence['source_origin'] == page['origin']
        horizontal = next(e for e in answer['evidence'] if e['details']['end'][0] == 10)
        x0, y0, x1, y1 = horizontal['bbox']
        assert (x0, x1) == (0, 10) and y0 < 0 < y1  # padded to stay visible, centred on y=0
        # INSERT and TEXT get boxes from their drawn (virtual) geometry too.
        insert = next(handle for handle, box in result['entities'].items() if box[1] == pytest.approx(5))
        assert result['entities'][insert][1:] == pytest.approx([5, -3, 6, -2])
        assert len(result['entities']) == 5
        # Saved answers keep the boxes.
        _, chat = request(base, path)
        assert chat['messages'][-1]['answer']['evidence'][0]['bbox']


def test_ifc_upload_gets_one_plan_page_per_storey_and_honest_door_boxes(tmp_path):
    content, ids = ifc_bytes()
    with running(tmp_path) as base:
        path, drawing = upload(base, 'building.ifc', content)
        preview, result = plan(base, drawing)
        assert result['status'] == 'ready' and result['layout'] == 'storeys'
        assert [(p['page'], p['label']) for p in result['pages']] == [(1, 'Ground'), (2, 'Upper')]
        assert result['entities'][ids['wall']] == [1, 0, -0.3, 10, 0]
        assert result['entities'][ids['door']] == [2, 2, -5.1, 3, -5]
        assert ids['bare'] not in result['entities']
        for page in result['pages']:
            status, raw = request(base, preview + '/' + str(page['page']))
            assert status == 200
            assert image(raw).shape[:2] == (page['pixel_height'], page['pixel_width'])
        upper = image(request(base, preview + '/2')[1])
        x, y = pixel(result['pages'][1], 2.5, 5.05)
        assert tuple(upper[y, x]) != (255, 255, 255)  # the door body is drawn
        assert request(base, preview + '/3')[0] == 404
        answer = ask(base, path, drawing, 'How many doors are there?')
        assert answer['value'] == 2
        boxed = {e['entity_id']: e for e in answer['evidence'] if 'bbox' in e}
        assert set(boxed) == {ids['door']}
        assert boxed[ids['door']]['page'] == 2 and boxed[ids['door']]['bbox'] == [2, -5.1, 3, -5]
        bare = next(e for e in answer['evidence'] if e['entity_id'] == ids['bare'])
        assert 'page' not in bare and 'preview_url' not in bare  # no geometry, plain id citation
        storeys = ask(base, path, drawing, 'How many storeys are there?')
        assert storeys['value'] == 2
        assert {e['entity_id']: e.get('page') for e in storeys['evidence']} == {ids['ground']: 1, ids['upper']: 2}
        assert not any('bbox' in e for e in storeys['evidence'])


def test_plan_geometry_runs_without_the_store_lock_and_is_cached(tmp_path, monkeypatch):
    from stoa_chat import native_preview
    release, calls, real = threading.Event(), [], native_preview._dxf
    def slow(path):
        calls.append(path)
        release.wait(10)
        return real(path)
    monkeypatch.setattr(native_preview, '_dxf', slow)
    with running(tmp_path) as base:
        path, drawing = upload(base, 'plan.dxf', dxf_bytes())
        preview = drawing['asset_url'].removeprefix('/api').replace('/assets/', '/previews/')
        status, result = request(base, preview)
        assert status == 202 and result == {'status': 'pending'}
        started = time.monotonic()
        assert request(base, path)[0] == 200  # chat routes stay responsive meanwhile
        assert request(base, preview)[0] == 202  # one job, not one per poll
        assert time.monotonic() - started < 5
        release.set()
        _, result = plan(base, drawing)
        assert result['status'] == 'ready' and len(calls) == 1
    cached = tmp_path / 'native_previews' / f"{drawing['sha256']}-v{native_preview.VERSION}"
    assert (cached / 'plan.json').is_file() and (cached / 'page-1.png').is_file()
    with running(tmp_path) as base:  # a restart reuses the disk cache
        assert plan(base, drawing)[1]['status'] == 'ready' and len(calls) == 1
        request(base, path, 'DELETE')
    with running(tmp_path):
        assert not cached.exists()  # removed with its last referencing chat


def test_bounded_geometry_degrades_to_a_stated_reason(tmp_path, monkeypatch):
    from stoa_chat import native_preview
    monkeypatch.setattr(native_preview, 'IFC_ELEMENT_CAP', 1)
    content, _ = ifc_bytes()
    with running(tmp_path) as base:
        path, drawing = upload(base, 'building.ifc', content)
        preview, result = plan(base, drawing)
        assert result['status'] == 'unavailable'
        assert 'plan view limit is 1' in result['reason']
        assert request(base, preview + '/1')[0] == 404
        answer = ask(base, path, drawing, 'How many doors are there?')
        assert answer['value'] == 2 and not any('page' in e for e in answer['evidence'])


def test_ifc_without_body_geometry_has_no_plan_but_keeps_id_evidence(tmp_path):
    import ifcopenshell
    model = ifcopenshell.file(schema='IFC4')
    model.create_entity('IfcProject', GlobalId=ifcopenshell.guid.new(), Name='Bare')
    door = model.create_entity('IfcDoor', GlobalId=ifcopenshell.guid.new(), Name='Door')
    with running(tmp_path) as base:
        path, drawing = upload(base, 'bare.ifc', model.to_string().encode())
        _, result = plan(base, drawing)
        assert result['status'] == 'unavailable' and result['reason']
        answer = ask(base, path, drawing, 'How many doors are there?')
        assert answer['evidence'][0]['entity_id'] == door.GlobalId and 'bbox' not in answer['evidence'][0]
