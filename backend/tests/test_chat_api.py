import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager

from stoa_chat import create_server


@contextmanager
def running(root, answerer=None, **kwargs):
    server = create_server(root, port=0, answerer=answerer, **kwargs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def request(base, path, method='GET', data=None, headers=None):
    headers = headers or {}
    if isinstance(data, (dict, list)):
        data = json.dumps(data).encode()
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(base + '/api' + path, data=data, method=method, headers=headers)
    try:
        response = urllib.request.urlopen(req)
    except urllib.error.HTTPError as exc:
        response = exc
    raw = response.read()
    return response.status, json.loads(raw) if response.headers.get_content_type() == 'application/json' else raw


def test_chat_survives_restart_and_can_be_deleted(tmp_path):
    with running(tmp_path) as base:
        status, chat = request(base, '/chats', 'POST', {'title': 'House'})
        assert status == 201
        chat_id = chat['id']
    with running(tmp_path) as base:
        assert request(base, '/chats')[1][0]['title'] == 'House'
        assert request(base, f'/chats/{chat_id}')[1]['messages'] == []
        assert request(base, f'/chats/{chat_id}', 'DELETE')[0] == 200
        assert request(base, f'/chats/{chat_id}')[0] == 404


def png():
    import cv2
    import numpy as np
    return cv2.imencode('.png', np.zeros((12, 16, 3), dtype=np.uint8))[1].tobytes()


def test_upload_ask_follow_up_and_scoped_evidence_survive_restart(tmp_path):
    def answer(context):
        drawing = context['drawings'][0]
        assert drawing['path'].read_bytes() == png()
        return {'status': 'proposal', 'value': 0, 'unit': 'count', 'explanation': 'No chairs marked',
                'evidence': [{'drawing_id': drawing['id'], 'page': 1, 'bbox': [0, 0, 16, 12]}],
                'prior_messages': len(context['messages'])}
    with running(tmp_path, answer) as base:
        chat = request(base, '/chats', 'POST', {})[1]
        path = '/chats/' + chat['id']
        status, drawing = request(base, path + '/uploads?filename=plan.png', 'POST', png())
        assert status == 201
        assert drawing['format'] == 'png'
        status, first = request(base, path + '/questions', 'POST', {'question': 'How many chairs?', 'drawing_ids': [drawing['id']]})
        assert status == 200
        assert first['answer']['value'] == 0
        second = request(base, path + '/questions', 'POST', {'question': 'Entä tässä?'})[1]
        assert second['answer']['prior_messages'] == 2
        assert second['drawing_ids'] == [drawing['id']]
        evidence_url = first['answer']['evidence'][0]['url']
        assert request(base, evidence_url.removeprefix('/api'))[1]['bbox'] == [0, 0, 16, 12]
        assert request(base, path + '/assets/' + drawing['id'])[1] == png()
        other = request(base, '/chats', 'POST', {})[1]
        assert request(base, '/chats/' + other['id'] + '/assets/' + drawing['id'])[0] == 404
    with running(tmp_path) as base:
        restored = request(base, path)[1]
        assert len(restored['messages']) == 4
        assert restored['selected_drawing_ids'] == [drawing['id']]
        assert request(base, evidence_url.removeprefix('/api'))[0] == 200


def test_all_six_formats_validate_contents_and_preserve_originals(tmp_path):
    import cv2
    import ezdxf
    import ifcopenshell
    import io
    import numpy as np
    import pymupdf
    pdf = pymupdf.open()
    pdf.new_page(width=100, height=200)
    pdf.new_page(width=300, height=400)
    dxf = ezdxf.new()
    dxf.modelspace().add_line((0, 0), (3, 4))
    stream = io.StringIO()
    dxf.write(stream)
    ifc = ifcopenshell.file(schema='IFC4')
    ifc.create_entity('IfcProject', GlobalId=ifcopenshell.guid.new(), Name='Test')
    fixtures = [('image.png', png(), 'png'),
                ('image.jpg', cv2.imencode('.jpg', np.zeros((12,16,3), dtype=np.uint8))[1].tobytes(), 'jpeg'),
                ('drawing.pdf', pdf.tobytes(), 'pdf'),
                ('model.ifc', ifc.to_string().encode(), 'ifc'),
                ('drawing.dxf', stream.getvalue().encode(), 'dxf'),
                ('drawing.svg', b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 20"><rect id="room" width="10" height="20"/></svg>', 'svg')]
    with running(tmp_path) as base:
        path = '/chats/' + request(base, '/chats', 'POST', {})[1]['id']
        for name, content, format in fixtures:
            status, drawing = request(base, path + '/uploads?filename=' + name, 'POST', content)
            assert status == 201, drawing
            assert drawing['format'] == format
            assert request(base, path + '/assets/' + drawing['id'])[1] == content
            if format == 'pdf':
                assert len(drawing['pages']) == 2
        for name, content in [('fake.png', b'garbage'), ('wrong.jpg', png()),
                              ('bad.svg', b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'),
                              ('bad.svg', b'<svg xmlns="http://www.w3.org/2000/svg"><image href="https://evil/a"/></svg>'),
                              ('bad.ifc', b'ISO-10303-21;garbage'), ('bad.dxf', b'0\nSECTION\n2\nENTITIES\n'),
                              ('bad.pdf', b'%PDF-garbage')]:
            assert request(base, path + '/uploads?filename=' + name, 'POST', content)[0] == 400


def test_invalid_requests_and_provider_failure_preserve_history(tmp_path):
    def broken(context):
        raise RuntimeError('private provider detail')
    with running(tmp_path, broken, max_upload_bytes=1000) as base:
        path = '/chats/' + request(base, '/chats', 'POST', {})[1]['id']
        assert request(base, '/chats', 'POST', {}, {'Origin': 'https://evil.example'})[0] == 403
        assert request(base, '/chats', 'POST', b'{')[0] == 400
        assert request(base, '/chats', 'POST', [])[0] == 400
        assert request(base, path + '/uploads?filename=x.png', 'POST', b'x' * 1001)[0] == 413
        drawing = request(base, path + '/uploads?filename=x.png', 'POST', png())[1]
        assert request(base, path + '/questions', 'POST', {'question': 'count', 'drawing_ids': ['unknown']})[0] == 400
        assert request(base, path + '/questions', 'POST', {'question': ' ', 'drawing_ids': [drawing['id']]})[0] == 400
        answer = request(base, path + '/questions', 'POST', {'question': 'Count fixtures', 'drawing_ids': [drawing['id']]})[1]['answer']
        assert answer['status'] == 'abstain' and answer['value'] is None
        assert answer['error'] == 'analysis_error'
        assert len(request(base, path)[1]['messages']) == 2
    with running(tmp_path) as base:
        assert request(base, path + '/questions', 'POST', {'question': 'Again'})[1]['answer']['status'] == 'abstain'
        assert len(request(base, path)[1]['messages']) == 4


def test_fabricated_evidence_or_malformed_answers_become_saved_abstains(tmp_path):
    outputs = [None, {'status': 'supported', 'value': 5, 'evidence': []},
               {'status': 'proposal', 'value': 5, 'evidence': [{'drawing_id': 'invented'}]},
               {'status': 'supported', 'value': float('nan'), 'evidence': []}]
    def answer(context):
        drawing = context['drawings'][0]
        output = outputs.pop(0)
        if output == 'page':
            return {'status': 'proposal', 'value': 5, 'evidence': [{'drawing_id': drawing['id'], 'page': 99}]}
        if output == 'box':
            return {'status': 'proposal', 'value': 5, 'evidence': [{'drawing_id': drawing['id'], 'page': 1, 'bbox': [0, 0, 9999, 9999]}]}
        if output == 'entity':
            return {'status': 'proposal', 'value': 5, 'evidence': [{'drawing_id': drawing['id'], 'entity_id': 'fake'}]}
        return output
    outputs += ['page', 'box', 'entity']
    with running(tmp_path, answer) as base:
        path = '/chats/' + request(base, '/chats', 'POST', {})[1]['id']
        drawing = request(base, path + '/uploads?filename=x.png', 'POST', png())[1]
        for _ in range(7):
            status, message = request(base, path + '/questions', 'POST', {'question': 'count', 'drawing_ids': [drawing['id']]})
            assert status == 200
            assert message['answer']['status'] == 'abstain'
            assert message['answer']['value'] is None
            assert message['answer']['error'] == 'invalid_analysis'
        assert len(request(base, path)[1]['messages']) == 14


def test_delete_removes_unreferenced_material_but_keeps_shared_uploads(tmp_path):
    with running(tmp_path) as base:
        one = '/chats/' + request(base, '/chats', 'POST', {})[1]['id']
        two = '/chats/' + request(base, '/chats', 'POST', {})[1]['id']
        a = request(base, one + '/uploads?filename=one.png', 'POST', png())[1]
        b = request(base, two + '/uploads?filename=renamed.png', 'POST', png())[1]
        assert a['sha256'] == b['sha256']
        request(base, one, 'DELETE')
        assert request(base, two + '/assets/' + b['id'])[1] == png()
        assert request(base, one + '/assets/' + a['id'])[0] == 404
        request(base, two, 'DELETE')
        assert list((tmp_path / 'assets').iterdir()) == []


def test_frontend_can_be_served_same_origin_without_exposing_storage(tmp_path):
    frontend = tmp_path / 'frontend'
    frontend.mkdir()
    (frontend / 'index.html').write_text('<title>Drawing chat</title>')
    (tmp_path / 'secret.txt').write_text('private')
    with running(tmp_path / 'storage', static_dir=frontend) as base:
        response = urllib.request.urlopen(base + '/')
        assert b'Drawing chat' in response.read()
        assert response.headers['Content-Security-Policy']
        assert request(base, '/../secret.txt')[0] == 404


def test_binary_dxf_is_accepted_without_conversion_of_original(tmp_path):
    import ezdxf
    source = tmp_path / 'native.dxf'
    drawing = ezdxf.new()
    drawing.modelspace().add_circle((2, 3), 1)
    drawing.saveas(source, fmt='bin')
    content = source.read_bytes()
    with running(tmp_path / 'storage') as base:
        path = '/chats/' + request(base, '/chats', 'POST', {})[1]['id']
        status, uploaded = request(base, path + '/uploads?filename=drawing.dxf', 'POST', content)
        assert status == 201
        assert uploaded['entity_ids']
        assert request(base, path + '/assets/' + uploaded['id'])[1] == content
