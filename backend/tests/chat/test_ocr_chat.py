"""OCR in the drawing chat: source mapping, visible failures, coverage and the upload/question flow."""
import json
import cv2
import numpy as np
import pytest
from test_analysis_api import upload, ask
from test_chat_api import running
from stoa.lanes import llm
from stoa_chat import ocr, ocr_views
from stoa_chat.analysis import HybridAnswerer


@pytest.fixture(autouse=True)
def ocr_on(monkeypatch):
    monkeypatch.setenv('STOA_OCR', 'on')
    ocr_views._cache.clear()


def tok(text, box, conf=90.0):
    return {'text': text, 'bbox': box, 'confidence': conf, 'engine': 'tesseract', 'version': '5.test'}


def drawing(tmp_path, width, height=800):
    path = tmp_path / 'plan.png'
    path.write_bytes(cv2.imencode('.png', np.full((height, width, 3), 255, np.uint8))[1].tobytes())
    return {'id': 'drawing', 'filename': 'plan.png', 'path': path, 'format': 'png', 'sha256': 'srchash',
            'asset_url': '/api/chats/chat/assets/drawing', 'pages': [{'page': 1, 'width': width, 'height': height, 'units': 'px'}],
            'entity_ids': []}


def context(d, question='How many bedrooms marked mh?'):
    return {'question': question, 'drawing_ids': [d['id']], 'drawings': [d], 'messages': []}


def count_all_tiles(payloads):
    def respond(messages, **kw):
        p = json.loads(messages[1]['content'][0]['text']); payloads.append(p)
        return json.dumps({'operation': 'count', 'complete': True, 'coverage': p['required_coverage'], 'facts': []})
    return respond


def test_crop_boxes_map_to_source_pixels_exactly_once(tmp_path, monkeypatch):
    d = drawing(tmp_path, 3200)  # tiles start at x=0, 1120, 2240
    monkeypatch.setattr(ocr, 'extract_text', lambda image, langs=None: [tok('MH', [10, 20, 50, 40])])
    monkeypatch.setattr(llm, 'chat', count_all_tiles([]))
    answer = HybridAnswerer()(context(d))
    views = {v['view_id']: v for v in answer['ocr']['views']}
    assert list(views) == ['drawing:1:tile:0:0', 'drawing:1:tile:0:1', 'drawing:1:tile:0:2']
    for col, x in enumerate([0, 1120, 2240]):
        t = views[f'drawing:1:tile:0:{col}']['tokens'][0]
        assert t['bbox'] == [10, 20, 50, 40]                     # input-crop pixels preserved
        assert t['source_bbox'] == [10 + x, 20, 50 + x, 40]      # transformed once
        assert (t['text'], t['engine'], t['version'], t['confidence']) == ('MH', 'tesseract', '5.test', 90.0)
        assert t['source_sha256'] == 'srchash' and t['view_id'] == f'drawing:1:tile:0:{col}'


def test_every_tile_is_read_and_sent_with_status_even_when_ocr_finds_nothing(tmp_path, monkeypatch):
    d = drawing(tmp_path, 7000)
    calls, payloads = [], []
    monkeypatch.setattr(ocr, 'extract_text', lambda image, langs=None: calls.append(1) or [])
    monkeypatch.setattr(llm, 'chat', count_all_tiles(payloads))
    answer = HybridAnswerer()(context(d))
    assert answer['status'] == 'proposal' and answer['value'] == 0   # zero still needs full coverage, which held
    assert len(calls) == 6                                            # six tiles; the overview is not read
    assert {v['status'] for v in answer['ocr']['views']} == {'empty'}
    seen = [v['view_id'] for p in payloads for v in p['ocr']['views']]
    assert seen == [f'drawing:1:tile:0:{i}' for i in range(6)]
    assert answer['image_processing']['completed_views'] == answer['image_processing']['required_views']


def test_missing_engine_is_visible_and_vlm_only_path_still_answers(tmp_path, monkeypatch):
    d = drawing(tmp_path, 3200)
    def missing(image, langs=None):
        raise ocr.OcrUnavailable('tesseract binary not found on PATH; install tesseract to enable OCR')
    monkeypatch.setattr(ocr, 'extract_text', missing)
    monkeypatch.setattr(llm, 'chat', count_all_tiles([]))
    answer = HybridAnswerer()(context(d))
    assert answer['status'] == 'proposal' and answer['value'] == 0
    assert {v['status'] for v in answer['ocr']['views']} == {'unavailable'}
    assert all('not found' in v['error'] and v['tokens'] == [] for v in answer['ocr']['views'])
    assert answer['contributions'][0]['ocr']['views'][0]['status'] == 'unavailable'


def test_ocr_disabled_leaves_the_pipeline_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv('STOA_OCR', 'off')
    monkeypatch.setattr(ocr, 'extract_text', lambda *a, **k: pytest.fail('engine must not run'))
    payloads = []
    monkeypatch.setattr(llm, 'chat', count_all_tiles(payloads))
    answer = HybridAnswerer()(context(drawing(tmp_path, 3200)))
    assert answer['value'] == 0 and {v['status'] for v in answer['ocr']['views']} == {'disabled'}


def test_repeated_labels_keep_distinct_locations_and_overlap_dedupes_by_position(tmp_path, monkeypatch):
    d = drawing(tmp_path, 3200)
    def words(image, langs=None):  # every tile reports the same two "mh" words at the same crop pixels
        return [tok('mh', [100, 100, 140, 120]), tok('mh', [300, 100, 340, 120], 80.0)]
    monkeypatch.setattr(ocr, 'extract_text', words)
    def respond(messages, **kw):
        p = json.loads(messages[1]['content'][0]['text'])
        tile = next(v for v in p['pages'] if v.get('role') == 'detail')
        return json.dumps({'operation': 'count', 'complete': True, 'coverage': p['required_coverage'],
                           'facts': [{'page_ref': tile['id'], 'bbox': [95, 95, 145, 125], 'kind': 'text',
                                      'printed_text': 'mh', 'label': 'bedroom'},
                                     {'page_ref': tile['id'], 'bbox': [295, 95, 345, 125], 'kind': 'text',
                                      'printed_text': 'mh', 'label': 'bedroom'}]})
    monkeypatch.setattr(llm, 'chat', respond)
    answer = HybridAnswerer()(context(d))
    first = answer['evidence'][0]
    assert [t['text'] for t in first['ocr_support']] == ['mh']      # only the word inside this box
    # identical text at two places is not a duplicate: 2 words x 3 tiles at distinct source positions
    tokens = [t for r in answer['ocr']['views'] for t in r['tokens']]
    ev = [{'bbox': [0, 0, 3200, 800]}]
    ocr_views.attach_support(ev, [{'tokens': tokens}])
    assert len(ev[0]['ocr_support']) == 6 and len({tuple(t['source_bbox']) for t in ev[0]['ocr_support']}) == 6
    same_place = [{**tokens[0], 'id': 'x', 'view_id': 'other', 'confidence': 95.0}, tokens[0]]
    ev = [{'bbox': [0, 0, 3200, 800]}]
    ocr_views.attach_support(ev, [{'tokens': same_place}])
    assert [t['id'] for t in ev[0]['ocr_support']] == ['x']          # higher score wins at one location


def test_printed_quantity_flows_through_python_calculation_with_ocr_hint(tmp_path, monkeypatch):
    d = drawing(tmp_path, 800, 600)
    monkeypatch.setattr(ocr, 'extract_text', lambda image, langs=None: [tok('12,5', [100, 100, 150, 120]), tok('m', [152, 100, 165, 120], 75.0),
                                                                          tok('~', [300, 300, 310, 310], 5.0)])
    seen = {}
    def respond(messages, **kw):
        p = json.loads(messages[1]['content'][0]['text']); seen.update(p)
        page = p['pages'][0]
        return json.dumps({'operation': 'sum', 'complete': True, 'coverage': [], 'facts': [
            {'page_ref': page['id'], 'bbox': [100, 100, 165, 120], 'kind': 'length', 'value': 12.5, 'unit': 'm', 'printed_text': '12,5 m'}]})
    monkeypatch.setattr(llm, 'chat', respond)
    answer = HybridAnswerer()(context(d, 'What is the total length of the printed dimension?'))
    assert answer['value'] == 12.5 and answer['unit'] == 'm' and answer['review_status'] == 'unreviewed'
    assert [t['text'] for t in seen['ocr']['views'][0]['tokens']] == ['12,5', 'm']    # low-score junk filtered
    assert seen['ocr']['views'][0]['tokens_omitted'] == 1 and 'not answer probabilities' in seen['ocr']['note']
    assert [t['text'] for t in answer['evidence'][0]['ocr_support']] == ['12,5', 'm']


def test_tokens_are_bounded_without_hiding_the_count(tmp_path, monkeypatch):
    d = drawing(tmp_path, 800, 600)
    words = [tok(f'w{i}', [i, 10, i + 1, 20], 40.0 + i % 50) for i in range(400)]
    monkeypatch.setattr(ocr, 'extract_text', lambda image, langs=None: words)
    record = ocr_views.read_view(b'bytes', {'id': 'v', 'transform': [1, 0, 0, 1, 0, 0]}, 's', {})
    assert len(record['tokens']) == ocr_views.MAX_TOKENS_PER_VIEW
    assert record['tokens_total'] == 400 and record['tokens_omitted'] == 300
    assert min(t['confidence'] for t in record['tokens']) >= 77   # best-scored words kept


def test_results_are_cached_per_view_and_engine_settings(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ocr, 'extract_text', lambda image, langs=None: calls.append(langs) or [tok('a', [1, 1, 5, 5])])
    view = {'id': 'v', 'transform': [1, 0, 0, 1, 0, 0]}
    for _ in range(2): ocr_views.read_view(b'bytes', view, 's', {})
    assert len(calls) == 1
    ocr_views.read_view(b'bytes', {**view, 'transform': [1, 0, 0, 1, 5, 0]}, 's', {})      # other transform
    monkeypatch.setenv('STOA_OCR_LANGS', 'eng')
    ocr_views.read_view(b'bytes', view, 's', {})                                            # other languages
    assert len(calls) == 3 and calls[-1] == ['eng']


def test_failures_are_not_cached_and_time_budget_reports_skipped(monkeypatch):
    state = {'fail': True}
    def flaky(image, langs=None):
        if state['fail']: raise ocr.OcrUnavailable('tesseract timed out after 30 seconds')
        return []
    monkeypatch.setattr(ocr, 'extract_text', flaky)
    view = {'id': 'v', 'transform': [1, 0, 0, 1, 0, 0]}
    assert ocr_views.read_view(b'b', view, 's', {})['status'] == 'unavailable'
    state['fail'] = False
    assert ocr_views.read_view(b'b', view, 's', {})['status'] == 'empty'
    expired = {'_ocr_deadline': -1}
    skipped = ocr_views.read_view(b'other', view, 's', expired)
    assert skipped['status'] == 'skipped' and skipped['tokens'] == []


def test_upload_question_flow_exposes_ocr_to_inspector_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, 'extract_text', lambda image, langs=None: [tok('MH', [100, 50, 200, 150])])
    def respond(messages, **kw):
        p = json.loads(messages[-1]['content'][0]['text'])
        tile = next(v for v in p['pages'] if v.get('role') == 'detail')
        return json.dumps({'operation': 'count', 'complete': True, 'coverage': p['required_coverage'],
                           'facts': [{'page_ref': tile['id'], 'bbox': [100, 50, 200, 150], 'kind': 'text', 'printed_text': 'MH'}]
                           if tile['id'].endswith(':0:0') else []})
    monkeypatch.setattr(llm, 'chat', respond)
    image = cv2.imencode('.png', np.full((800, 3200, 3), 255, np.uint8))[1].tobytes()
    with running(tmp_path) as base:
        path, d = upload(base, 'plan.png', image)
        answer = ask(base, path, d, 'How many bedrooms marked MH?')
        assert answer['value'] == 1 and answer['review_status'] == 'unreviewed'
        assert answer['ocr']['review_status'] == 'unreviewed'
        evidence = answer['evidence'][0]
        assert evidence['bbox'] == [100, 50, 200, 150] and evidence['ocr_support'][0]['text'] == 'MH'
        assert evidence['ocr_support'][0]['source_sha256'] == d['sha256']
        again = ask(base, path, d, 'How many bedrooms marked MH?')
        assert again['ocr']['views'][0]['tokens'][0]['source_bbox'] == [100, 50, 200, 150]
