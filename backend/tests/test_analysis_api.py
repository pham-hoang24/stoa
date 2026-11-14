"""Application behavior, controlled source facts; no real provider or benchmark files."""
import io
import json

from test_chat_api import running, request, png


def upload(base, name, content, path=None):
    path = path or '/chats/' + request(base, '/chats', 'POST', {})[1]['id']
    status, drawing = request(base, path + '/uploads?filename=' + name, 'POST', content)
    assert status == 201, drawing
    return path, drawing


def ask(base, path, drawing, question):
    status, message = request(base, path + '/questions', 'POST',
                              {'question': question, 'drawing_ids': [drawing['id']]})
    assert status == 200, message
    return message['answer']


def model():
    import ifcopenshell
    f = ifcopenshell.file(schema='IFC4')
    f.create_entity('IfcProject', GlobalId=ifcopenshell.guid.new(), Name='Studio')
    for name in ['North', 'South']:
        wall = f.create_entity('IfcWall', GlobalId=ifcopenshell.guid.new(), Name=name)
        quantity = f.create_entity('IfcQuantityArea', Name='NetSideArea', AreaValue=6.)
        qto = f.create_entity('IfcElementQuantity', GlobalId=ifcopenshell.guid.new(), Name='Qto_WallBaseQuantities', Quantities=[quantity])
        f.create_entity('IfcRelDefinesByProperties', GlobalId=ifcopenshell.guid.new(), RelatedObjects=[wall], RelatingPropertyDefinition=qto)
    return f.to_string().encode()


def test_default_native_ifc_count_then_area_followup_without_provider(tmp_path, monkeypatch):
    from stoa.lanes import llm
    monkeypatch.setattr(llm, 'chat', lambda *a, **k: (_ for _ in ()).throw(AssertionError('native path used provider')))
    with running(tmp_path) as base:
        path, drawing = upload(base, 'unrelated.ifc', model())
        answer = ask(base, path, drawing, 'How many walls?')
        assert answer['status'] == 'supported'
        assert answer['value'] == 2
        assert len(answer['evidence']) == 2
        assert all(e['entity_id'] in drawing['entity_ids'] for e in answer['evidence'])
        area = ask(base, path, drawing, 'What is their total area?')
        assert area['value'] == 12
        assert area['unit'] == 'm²'
        assert area['calculation']['operation'] == 'sum'
        assert all(e['property'] == 'Qto_WallBaseQuantities.NetSideArea' for e in area['evidence'])


def test_visual_count_maps_preview_regions_and_keeps_unreviewed_state(tmp_path, monkeypatch):
    import cv2
    import numpy as np
    from stoa.lanes import llm
    def extract(messages, **kwargs):
        payload = json.loads(messages[-1]['content'][0]['text'])
        page = payload['pages'][0]
        assert page['width'] == 1600 and page['source_width'] == 3200
        return json.dumps({'operation': 'count', 'complete': True, 'coverage': [page['id']],
                           'facts': [{'page_ref': page['id'], 'bbox': [100, 50, 200, 150], 'kind': 'object', 'label': 'sauna'}]})
    monkeypatch.setattr(llm, 'chat', extract)
    image = cv2.imencode('.png', np.zeros((800,3200,3), dtype=np.uint8))[1].tobytes()
    with running(tmp_path) as base:
        path, drawing = upload(base, 'random.png', image)
        answer = ask(base, path, drawing, 'Kuinka monta saunaa?')
        assert answer['value'] == 1
        assert answer['status'] == 'proposal'
        assert answer['review_status'] == 'unreviewed'
        evidence = answer['evidence'][0]
        assert evidence['bbox'] == [200,100,400,300]
        assert evidence['source_width'] == 3200
        preview = request(base, evidence['preview_url'].removeprefix('/api'))
        assert preview[0] == 200 and preview[1].startswith(b'\x89PNG')
