"""Regressions for the raster answer pipeline: provider replies, parsing, direct answers and grounding."""
import json
import os
from types import SimpleNamespace

import cv2
import numpy as np
import openai
import pytest

from stoa.lanes import llm
from stoa_chat import ocr, ocr_views
from stoa_chat.analysis import HybridAnswerer, question_kind
from stoa_chat.extraction import calculate, parse_plan, unit_printed, repeated_grid


# ---------- provider transport ----------

REAL_CHAT = llm.chat  # captured at import, before the suite's autouse stub replaces it

@pytest.fixture
def sdk(monkeypatch, tmp_path):
    monkeypatch.setattr(os, 'environ', os.environ.copy())
    for name in list(os.environ):
        if name.startswith(('STOA_LLM_', 'STOA_NVIDIA_', 'STOA_MODAL_')):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('NVIDIA_API_KEY', 'controlled-nvidia-key')
    monkeypatch.delenv('MODAL_API_KEY', raising=False)
    monkeypatch.setattr(llm, '_env', lambda: None)
    monkeypatch.setattr(llm, 'CACHE', tmp_path / 'cache')
    monkeypatch.setattr(llm, 'chat', REAL_CHAT)
    llm.reset_usage()
    state = SimpleNamespace(calls=[], replies=[])

    def client(**config):
        def create(**request):
            state.calls.append({'config': config, 'request': request})
            reply = state.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            content, finish = reply if isinstance(reply, tuple) else (reply, 'stop')
            return SimpleNamespace(usage=None, choices=[SimpleNamespace(
                finish_reason=finish, message=SimpleNamespace(content=content))])
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr(openai, 'OpenAI', client)
    return state


MESSAGES = [{'role': 'user', 'content': 'controlled'}]


def test_empty_and_truncated_replies_are_never_cached(sdk):
    sdk.replies = ['', ('{"operation": "co', 'length'), '{"ok": 1}']
    assert llm.chat(MESSAGES) == ''
    truncated = llm.chat(MESSAGES)
    assert truncated.provenance['finish_reason'] == 'length'
    assert llm.chat(MESSAGES) == '{"ok": 1}'
    assert len(sdk.calls) == 3                      # each retry reached the provider
    assert llm.chat(MESSAGES).provenance['cached']  # only the usable reply was cached
    assert len(sdk.calls) == 3


def test_legacy_empty_cache_file_is_not_replayed_and_forget_evicts(sdk):
    sdk.replies = ['first', 'second']
    reply = llm.chat(MESSAGES)
    reply.cache_file.write_text('')                 # an empty reply cached by the old transport
    assert llm.chat(MESSAGES) == 'second'
    cached = llm.chat(MESSAGES)
    assert cached.provenance['cached']
    llm.forget(cached)
    assert not cached.cache_file.exists()


def test_reasoning_off_is_sent_to_nvidia_and_keyed_separately(sdk):
    sdk.replies = ['a', 'b']
    llm.chat(MESSAGES, reasoning=False, timeout=150)
    assert sdk.calls[0]['request']['extra_body'] == {'chat_template_kwargs': {'enable_thinking': False}}
    assert sdk.calls[0]['config']['timeout'] == 150
    llm.chat(MESSAGES)
    assert 'extra_body' not in sdk.calls[1]['request'] and len(sdk.calls) == 2


def test_timeout_without_configured_fallback_says_so(sdk):
    import httpx2 as httpx
    sdk.replies = [openai.APITimeoutError(request=httpx.Request('POST', 'https://integrate.api.nvidia.com/v1'))]
    with pytest.raises(llm.ProviderTimeout, match='not configured.*MODAL_API_KEY'):
        llm.chat(MESSAGES)
    assert len(sdk.calls) == 1


# ---------- extraction ----------

def drawing(tmp_path, width=800, height=600):
    path = tmp_path / 'plan.png'
    path.write_bytes(cv2.imencode('.png', np.full((height, width, 3), 255, np.uint8))[1].tobytes())
    return {'id': 'drawing', 'filename': 'plan.png', 'path': path, 'format': 'png', 'sha256': 'hash',
            'asset_url': '/api/chats/chat/assets/drawing', 'pages': [{'page': 1, 'width': width, 'height': height, 'units': 'px'}],
            'entity_ids': []}


def ask(d, question, respond, monkeypatch):
    monkeypatch.setattr(llm, 'chat', respond)
    return HybridAnswerer()({'question': question, 'drawing_ids': [d['id']], 'drawings': [d], 'messages': []})


def page_of(messages):
    return json.loads(messages[1]['content'][0]['text'])['pages'][0]


def test_fenced_json_with_prose_is_accepted(tmp_path, monkeypatch):
    def respond(messages, **kw):
        p = page_of(messages)
        plan = {'operation': 'answer', 'complete': True, 'answer': '1:200', 'facts': [
            {'page_ref': p['id'], 'coordinate_space': 'normalized_1000', 'bbox': [700, 880, 800, 900],
             'kind': 'text', 'label': 'scale', 'printed_text': 'Massstab 1:200'}]}
        return 'Here is the extraction:\n```json\n' + json.dumps(plan) + '\n```\nDone.'
    answer = ask(drawing(tmp_path), 'What is the scale of this drawing?', respond, monkeypatch)
    assert answer['status'] == 'proposal' and answer['value'] == '1:200'
    assert answer['evidence'][0]['printed_text'] == 'Massstab 1:200'
    assert answer['evidence'][0]['bbox'] == pytest.approx([560, 528, 640, 540])
    assert parse_plan('{"a": {"b": 1}} trailing {') == {'a': {'b': 1}}


def test_empty_reply_is_resampled_without_a_correction_message(tmp_path, monkeypatch):
    calls = []
    def respond(messages, **kw):
        calls.append(len(messages))
        assert kw.get('reasoning') is False and kw['max_tokens'] >= 4000
        if len(calls) == 1:
            return ''
        p = page_of(messages)
        return json.dumps({'operation': 'text', 'complete': True, 'facts': [
            {'page_ref': p['id'], 'bbox': [1, 1, 50, 20], 'kind': 'text', 'printed_text': 'KITCHEN'}]})
    answer = ask(drawing(tmp_path), 'What label is shown?', respond, monkeypatch)
    assert answer['value'] == 'KITCHEN' and calls == [2, 2]


def plan_answer(page, facts, reply='Yes, a balcony is shown.'):
    return {'operation': 'answer', 'complete': True, 'answer': reply, 'facts': facts}


PAGE = {'id': 'd:1', 'drawing_id': 'd', 'page': 1, 'width': 1000, 'height': 500, 'source_width': 1000,
        'source_height': 500, 'source_origin': [0, 0], 'transform': [1, 0, 0, 1, 0, 0]}
D = [{'id': 'd', 'entity_ids': []}]


def test_direct_answer_requires_valid_cited_evidence():
    good = {'page_ref': 'd:1', 'bbox': [10, 10, 200, 100], 'kind': 'object', 'label': 'balcony'}
    answer = calculate(plan_answer(PAGE, [good]), {'d:1': PAGE}, {}, 'text', D, ['d:1'])
    assert answer['value'] == 'Yes, a balcony is shown.' and answer['review_status'] == 'unreviewed'
    assert answer['status'] == 'proposal' and answer['calculation']['operation'] == 'answer'
    for facts in ([], [{**good, 'bbox': [5000, 0, 6000, 10]}], [{**good, 'kind': 'text'}]):
        with pytest.raises(ValueError, match='direct answer needs cited evidence'):
            calculate(plan_answer(PAGE, facts), {'d:1': PAGE}, {}, 'text', D, ['d:1'])


def test_direct_answer_cannot_replace_counts_or_invent_quantities():
    area = {'page_ref': 'd:1', 'bbox': [10, 10, 200, 100], 'kind': 'text', 'printed_text': '31.05 m²'}
    name = {'page_ref': 'd:1', 'bbox': [10, 110, 200, 140], 'kind': 'text', 'printed_text': 'Reduit 2.30'}
    ok = calculate(plan_answer(PAGE, [area, name], 'Reduit 2.30, 31.05 m²'), {'d:1': PAGE}, {}, 'area', D, ['d:1'])
    assert ok['value'] == 'Reduit 2.30, 31.05 m²' and len(ok['evidence']) == 2
    named = calculate(plan_answer(PAGE, [area], 'Zimmer 2.27 is largest at 31.05 m²'), {'d:1': PAGE}, {}, 'area', D, ['d:1'])
    assert named['value'].endswith('31.05 m²')  # room numbers are names, not quantities
    for reply in ('About 40 m²', 'Zimmer 2.27'):
        with pytest.raises(ValueError, match='not printed'):
            calculate(plan_answer(PAGE, [area], reply), {'d:1': PAGE}, {}, 'area', D, ['d:1'])
    with pytest.raises(ValueError, match='Counts must be calculated'):
        calculate(plan_answer(PAGE, [area], '3'), {'d:1': PAGE}, {}, 'count', D, ['d:1'])


def test_direct_answer_drops_one_malformed_citation_and_says_so():
    good = {'page_ref': 'd:1', 'bbox': [10, 10, 200, 100], 'kind': 'object', 'label': 'balcony'}
    answer = calculate(plan_answer(PAGE, [good, {'page_ref': 'nope', 'bbox': [1, 1, 2, 2], 'kind': 'object'}]),
                       {'d:1': PAGE}, {}, 'text', D, ['d:1'])
    assert len(answer['evidence']) == 1 and answer['calculation']['dropped_facts'] == 1
    assert 'left out' in answer['explanation']


def test_small_overshoot_is_clamped_and_large_rejected():
    plan = {'operation': 'count', 'complete': True, 'facts': [
        {'page_ref': 'd:1', 'bbox': [-5, 10, 1015, 505], 'kind': 'object', 'label': 'sheet'}]}
    answer = calculate(plan, {'d:1': PAGE}, {}, 'count', D, ['d:1'])
    assert answer['evidence'][0]['bbox'] == [0, 10, 1000, 500] and answer['evidence'][0]['clamped']
    plan['facts'][0]['bbox'] = [0, 10, 1100, 400]
    with pytest.raises(ValueError, match='outside'):
        calculate(plan, {'d:1': PAGE}, {}, 'count', D, ['d:1'])


def test_count_never_drops_a_fact_silently():
    plan = {'operation': 'count', 'complete': True, 'facts': [
        {'page_ref': 'd:1', 'bbox': [10, 10, 20, 20], 'kind': 'object', 'label': 'door'},
        {'page_ref': 'd:1', 'bbox': [10, 10, 20, 20, 30], 'kind': 'object', 'label': 'door'}]}
    with pytest.raises(ValueError):
        calculate(plan, {'d:1': PAGE}, {}, 'count', D, ['d:1'])


def test_repeated_grid_of_boxes_is_not_a_count():
    grid = [[100, 100 + 20 * i, 120, 120 + 20 * i] for i in range(12)]
    assert repeated_grid(grid)
    assert not repeated_grid([[100 * i, 50, 100 * i + 30, 80] for i in range(9)])
    rooms = [[x, y, x + 124, y + 96] for x in (1190, 1364) for y in (158, 254, 350, 446, 542, 638)]
    assert not repeated_grid(rooms)  # two columns of six equal rooms are real, not a loop
    block = [[x, y, x + 124, y + 96] for x in (1190, 1314) for y in (158, 254, 350, 446, 542, 638)]
    assert not repeated_grid(block)  # even when the two columns share a wall
    assert repeated_grid([[100 + 20 * i, 100 + 20 * i, 120 + 20 * i, 120 + 20 * i] for i in range(15)])  # diagonal loop
    plan = {'operation': 'count', 'complete': True,
            'facts': [{'page_ref': 'd:1', 'bbox': b, 'kind': 'object', 'label': 'door'} for b in grid]}
    with pytest.raises(ValueError, match='grid'):
        calculate(plan, {'d:1': PAGE}, {}, 'count', D, ['d:1'])


@pytest.mark.parametrize('question,kind', [
    ('What is on the countertop?', 'text'), ('Which account number is printed?', 'text'),
    ('Count the doors', 'count'), ('How many doors are there?', 'count'),
    ('Is there a balcony?', 'text'), ('What is the area of the largest room?', 'area'),
    ('How high is the ceiling according to the note?', 'length')])
def test_question_kind(question, kind):
    assert question_kind(question) == kind


def test_length_question_can_be_answered_from_a_printed_note():
    note = {'page_ref': 'd:1', 'bbox': [10, 10, 200, 40], 'kind': 'text', 'printed_text': 'Ceiling height 2.6 m'}
    answer = calculate(plan_answer(PAGE, [note], '2.6 m'), {'d:1': PAGE}, {}, 'length', D, ['d:1'])
    assert answer['value'] == '2.6 m'
    text = calculate({'operation': 'text', 'complete': True, 'facts': [note]}, {'d:1': PAGE}, {}, 'length', D, ['d:1'])
    assert text['value'] == 'Ceiling height 2.6 m'


def test_unit_must_be_printed_as_its_own_token():
    assert not unit_printed('m', 'Bedroom')
    assert not unit_printed('m', '15.61 m²')
    assert unit_printed('m', '2.5 m') and unit_printed('m²', '15.61 m²') and unit_printed('mm', '2500mm')
    fact = {'page_ref': 'd:1', 'bbox': [1, 1, 50, 20], 'kind': 'length', 'value': 3, 'unit': 'm', 'printed_text': '3 Bedroom'}
    with pytest.raises(ValueError, match='printed value and unit'):
        calculate({'operation': 'sum', 'complete': True, 'facts': [fact]}, {'d:1': PAGE}, {}, 'length', D, ['d:1'])


def test_short_abstain_reason_becomes_a_full_sentence():
    answer = calculate({'operation': 'abstain', 'missing': 'room dimensions or scale factor'}, {}, {}, 'area', D, [])
    assert answer['explanation'] == 'This cannot be answered from the drawing alone. Missing: room dimensions or scale factor.'
    full = 'The plan is marked not to scale and prints no dimensions, so room areas cannot be measured.'
    assert calculate({'operation': 'abstain', 'missing': full}, {}, {}, 'area', D, [])['explanation'] == full


def test_large_image_non_count_question_no_longer_abstains(tmp_path, monkeypatch):
    d = drawing(tmp_path, 20000, 600)   # previously 18 detail regions > 12 → automatic abstain
    def respond(messages, **kw):
        p = page_of(messages)
        assert sum(c['type'] == 'image_url' for c in messages[1]['content']) == 1
        return json.dumps(plan_answer(p, [{'page_ref': p['id'], 'coordinate_space': 'normalized_1000',
                                           'bbox': [900, 100, 950, 200], 'kind': 'text', 'printed_text': 'SITE PLAN'}],
                                      'SITE PLAN'))
    answer = ask(d, 'What is the title of this drawing?', respond, monkeypatch)
    assert answer['status'] == 'proposal' and answer['value'] == 'SITE PLAN'
    assert answer['evidence'][0]['bbox'][0] == pytest.approx(18000) and answer['evidence'][0]['source_width'] == 20000


def test_failed_tile_batch_is_retried_and_completed_batches_kept(tmp_path, monkeypatch):
    d = drawing(tmp_path, 7000, 600)
    calls = []
    def respond(messages, **kw):
        p = json.loads(messages[1]['content'][0]['text'])
        calls.append(tuple(p['required_coverage']))
        if calls[-1] != calls[0] and calls.count(calls[-1]) <= 2:
            return '{'  # the second batch fails both attempts of its first try
        return json.dumps({'operation': 'count', 'complete': True, 'coverage': p['required_coverage'], 'facts': []})
    answer = ask(d, 'How many doors are there?', respond, monkeypatch)
    assert answer['status'] == 'proposal' and answer['value'] == 0
    assert answer['image_processing']['retried_batches'] == [2]
    assert answer['image_processing']['completed_views'] == answer['image_processing']['required_views']
    assert calls.count(calls[0]) == 1 and len(calls) == 4   # first batch never re-asked


def test_ocr_words_tighten_a_loose_text_box(tmp_path, monkeypatch):
    monkeypatch.setenv('STOA_OCR', 'on')
    ocr_views._cache.clear()
    tokens = [{'text': w, 'bbox': b, 'confidence': 90.0, 'engine': 'tesseract', 'version': '5.test'}
              for w, b in [('Massstab', [600, 500, 660, 515]), ('1:200', [665, 500, 700, 515]),
                           ('1:200', [100, 100, 135, 115])]]   # same text far away is ignored
    monkeypatch.setattr(ocr, 'extract_text', lambda image, langs=None: tokens)
    def respond(messages, **kw):
        p = page_of(messages)
        return json.dumps(plan_answer(p, [{'page_ref': p['id'], 'bbox': [560, 470, 760, 545], 'kind': 'text',
                                           'printed_text': 'Massstab 1:200'}], '1:200'))
    answer = ask(drawing(tmp_path), 'What is the scale?', respond, monkeypatch)
    ev = answer['evidence'][0]
    assert ev['bbox'] == [600, 500, 700, 515] and ev['bbox_source'] == 'ocr'
    assert ev['model_bbox'] == [560, 470, 760, 545] and ev['ocr_match']['matched_fraction'] == 1
    assert all('_snap' not in v for v in answer['ocr']['views'])


def test_ocr_does_not_snap_to_unrelated_words(tmp_path, monkeypatch):
    monkeypatch.setenv('STOA_OCR', 'on')
    ocr_views._cache.clear()
    monkeypatch.setattr(ocr, 'extract_text', lambda image, langs=None: [
        {'text': 'Kitchen', 'bbox': [600, 500, 660, 515], 'confidence': 90.0, 'engine': 'tesseract', 'version': '5.test'}])
    def respond(messages, **kw):
        p = page_of(messages)
        return json.dumps(plan_answer(p, [{'page_ref': p['id'], 'bbox': [560, 470, 760, 545], 'kind': 'text',
                                           'printed_text': 'Massstab 1:200'}], '1:200'))
    ev = ask(drawing(tmp_path), 'What is the scale?', respond, monkeypatch)['evidence'][0]
    assert ev['bbox'] == [560, 470, 760, 545] and 'bbox_source' not in ev


def test_null_optional_fields_mean_absent():
    fact = {'page_ref': 'd:1', 'bbox': [10, 10, 200, 100], 'kind': 'object', 'label': 'sauna',
            'printed_text': None, 'polygon': None, 'dimension_line': None, 'value': None, 'unit': None}
    answer = calculate({'operation': 'answer', 'complete': True, 'answer': 'Yes, a sauna is shown.', 'target': None,
                        'missing': None, 'estimate': None, 'facts': [fact]}, {'d:1': PAGE}, {}, 'text', D, ['d:1'])
    assert answer['value'] == 'Yes, a sauna is shown.' and answer['target'] == '' and 'polygon' not in answer['evidence'][0]


def test_truncated_reply_is_not_echoed_back(tmp_path, monkeypatch):
    seen = []
    def respond(messages, **kw):
        seen.append(messages)
        if len(seen) == 1:
            return llm.Completion('{"operation": "count", "facts": [{"bbox": [1,', {'provider': 'nvidia'}, 'm', finish_reason='length')
        p = page_of(messages)
        return json.dumps({'operation': 'count', 'complete': True, 'facts': [
            {'page_ref': p['id'], 'bbox': [10, 10, 40, 40], 'kind': 'object', 'label': 'door by the entrance'}]})
    answer = ask(drawing(tmp_path), 'How many doors are there?', respond, monkeypatch)
    assert answer['value'] == 1
    assert all(m['role'] != 'assistant' for m in seen[1]) and 'cut off' in seen[1][-1]['content']


def test_ocr_snap_needs_the_label_number_and_folds_accents(tmp_path, monkeypatch):
    monkeypatch.setenv('STOA_OCR', 'on')
    ocr_views._cache.clear()
    words = [('Zimmer', [300, 300, 340, 312]), ('2.27', [305, 314, 330, 324]), ('Kuche', [500, 100, 540, 112]), ('2.02', [505, 114, 530, 124])]
    monkeypatch.setattr(ocr, 'extract_text', lambda image, langs=None: [
        {'text': w, 'bbox': b, 'confidence': 90.0, 'engine': 'tesseract', 'version': '5.test'} for w, b in words])
    def respond(messages, **kw):
        p = page_of(messages)
        return json.dumps({'operation': 'text', 'complete': True, 'facts': [
            {'page_ref': p['id'], 'bbox': [290, 240, 350, 290], 'kind': 'text', 'printed_text': 'Zimmer 2.22'},
            {'page_ref': p['id'], 'bbox': [490, 90, 560, 140], 'kind': 'text', 'printed_text': 'Küche 2.02'}]})
    zimmer, kuche = ask(drawing(tmp_path), 'Which rooms are labelled?', respond, monkeypatch)['evidence']
    assert 'bbox_source' not in zimmer          # "Zimmer" alone near the box, but 2.22 is not there
    assert kuche['bbox'] == [500, 100, 540, 124] and kuche['bbox_source'] == 'ocr'


def test_count_boxes_on_blank_paper_are_rejected(tmp_path, monkeypatch):
    d = drawing(tmp_path)
    path = d['path']
    image = np.full((600, 800, 3), 255, np.uint8)
    for x in range(50, 750, 100):
        cv2.rectangle(image, (x, 50), (x + 40, 90), (0, 0, 0), 3)   # seven drawn doors along the top
    path.write_bytes(cv2.imencode('.png', image)[1].tobytes())
    def respond(messages, **kw):
        p = page_of(messages)
        drawn = [[x - i, 50 - i, x + 40 + i, 90] for i, x in enumerate(range(50, 750, 100))]
        empty = [[x, 400, x + 30 + 5 * i, 440] for i, x in enumerate(range(50, 450, 100))]   # four boxes on empty paper
        return json.dumps({'operation': 'count', 'complete': True, 'facts': [
            {'page_ref': p['id'], 'bbox': b, 'kind': 'object', 'label': f'door {i}'} for i, b in enumerate(drawn + empty)]})
    answer = ask(d, 'How many doors are there?', respond, monkeypatch)
    assert answer['status'] == 'abstain' and 'empty paper' in answer['explanation']
    def honest(messages, **kw):
        p = page_of(messages)
        return json.dumps({'operation': 'count', 'complete': True, 'facts': [
            {'page_ref': p['id'], 'bbox': [x - 2, 48, x + 42, 92], 'kind': 'object', 'label': f'door {x}'} for x in range(50, 750, 100)]})
    assert ask(d, 'How many doors are there?', honest, monkeypatch)['value'] == 7


def test_identical_stamped_object_boxes_are_not_a_count():
    from stoa_chat.extraction import uniform_boxes
    stamps = [[100 + 70 * (i % 2), 20 + 45 * i, 137 + 70 * (i % 2), 46 + 45 * i] for i in range(10)]
    assert uniform_boxes(stamps)
    varied = [[100 * i, 50, 100 * i + 30 + 7 * i, 80 + 5 * i] for i in range(10)]
    assert not uniform_boxes(varied)
    plan = {'operation': 'count', 'complete': True,
            'facts': [{'page_ref': 'd:1', 'bbox': b, 'kind': 'object', 'label': f'door {i}'} for i, b in enumerate(stamps)]}
    with pytest.raises(ValueError, match='grid'):
        calculate(plan, {'d:1': PAGE}, {}, 'count', D, ['d:1'])
    plan['facts'] = [{**f, 'kind': 'text', 'printed_text': 'Zimmer'} for f in plan['facts']]
    assert calculate(plan, {'d:1': PAGE}, {}, 'count', D, ['d:1'])['value'] == 10  # printed labels are uniform


def test_ocr_snap_spans_a_wide_gap_on_one_line(tmp_path, monkeypatch):
    monkeypatch.setenv('STOA_OCR', 'on')
    ocr_views._cache.clear()
    words = [('Massstab', [400, 300, 470, 313]), ('1:200', [560, 300, 600, 313]), ('(A3)', [605, 300, 630, 313])]
    monkeypatch.setattr(ocr, 'extract_text', lambda image, langs=None: [
        {'text': w, 'bbox': b, 'confidence': 90.0, 'engine': 'tesseract', 'version': '5.test'} for w, b in words])
    def respond(messages, **kw):
        p = page_of(messages)
        return json.dumps(plan_answer(p, [{'page_ref': p['id'], 'bbox': [390, 295, 640, 330], 'kind': 'text',
                                           'printed_text': 'Massstab 1:200 (A3)'}], '1:200'))
    ev = ask(drawing(tmp_path), 'What is the scale?', respond, monkeypatch)['evidence'][0]
    assert ev['bbox'] == [400, 300, 630, 313] and ev['bbox_source'] == 'ocr'
