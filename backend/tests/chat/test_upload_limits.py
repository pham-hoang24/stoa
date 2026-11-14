import hashlib

import ifcopenshell

from test_chat_api import request, running


def model(padding=0):
    drawing = ifcopenshell.file(schema='IFC4')
    drawing.create_entity('IfcProject', GlobalId=ifcopenshell.guid.new(), Name='Large model')
    return drawing.to_string().encode().replace(b'DATA;', b' ' * padding + b'\nDATA;', 1)


def test_ifc_larger_than_old_limit_uploads_and_persists(tmp_path):
    content = model(51 * 1024 * 1024)
    with running(tmp_path) as base:
        path = '/chats/' + request(base, '/chats', 'POST', {})[1]['id']
        status, drawing = request(base, path + '/uploads?filename=large.IFC', 'POST', content)
        assert status == 201, drawing
        assert drawing['format'] == 'ifc'
        assert drawing['sha256'] == hashlib.sha256(content).hexdigest()
        identifier = drawing['id']
    with running(tmp_path) as base:
        assert request(base, path)[1]['drawings'][0]['id'] == identifier


def test_published_limits_match_format_specific_upload_enforcement(tmp_path):
    with running(tmp_path, max_upload_bytes=1000, max_ifc_upload_bytes=2000) as base:
        status, config = request(base, '/config')
        assert status == 200
        assert config['upload_limits'] == {'default': 1000, 'ifc': 2000}
        path = '/chats/' + request(base, '/chats', 'POST', {})[1]['id']
        assert request(base, path + '/uploads?filename=model.ifc', 'POST', model(1000))[0] == 201
        assert request(base, path + '/uploads?filename=model.ifc', 'POST', model(2000))[0] == 413
        assert request(base, path + '/uploads?filename=image.png', 'POST', b'x' * 1001)[0] == 413
        assert request(base, path + '/uploads?filename=renamed.ifc', 'POST', b'x' * 1200)[0] == 400


def test_default_limits_allow_large_ifc_without_raising_other_format_limits(tmp_path):
    with running(tmp_path) as base:
        assert request(base, '/config')[1]['upload_limits'] == {
            'default': 50 * 1024 * 1024, 'ifc': 512 * 1024 * 1024,
        }
