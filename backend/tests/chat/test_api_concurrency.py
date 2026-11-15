import threading
import time

from stoa_chat import api
from test_chat_api import png, request, running


IDS = {}


def ask_in_thread(base, path, results, key='r'):
    def run():
        results[key] = request(base, path + '/questions', 'POST', {'question': 'How many?', 'drawing_ids': IDS[path]})
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def setup_chat(base):
    chat = request(base, '/chats', 'POST', {})[1]
    path = '/chats/' + chat['id']
    drawing = request(base, path + '/uploads?filename=plan.png', 'POST', png())[1]
    IDS[path] = [drawing['id']]
    return chat['id'], path


def blocked_answerer():
    started, release = threading.Event(), threading.Event()

    def answer(context):
        started.set()
        assert release.wait(5)
        return {'status': 'abstain', 'explanation': 'blocked', 'evidence': []}
    return answer, started, release


def test_other_requests_not_blocked_by_inflight_question(tmp_path):
    answer, started, release = blocked_answerer()
    with running(tmp_path, answer) as base:
        _, path = setup_chat(base)
        results = {}
        thread = ask_in_thread(base, path, results)
        try:
            assert started.wait(5)
            t0 = time.monotonic()
            assert request(base, '/chats')[0] == 200
            status, chat = request(base, path)
            assert status == 200
            assert [m['role'] for m in chat['messages']] == ['user']
            assert time.monotonic() - t0 < 1
        finally:
            release.set()
            thread.join(5)
        assert results['r'][0] == 200
        assert [m['role'] for m in request(base, path)[1]['messages']] == ['user', 'assistant']


def test_delete_mid_question_does_not_resurrect_chat(tmp_path):
    answer, started, release = blocked_answerer()
    with running(tmp_path, answer) as base:
        chat_id, path = setup_chat(base)
        results = {}
        thread = ask_in_thread(base, path, results)
        try:
            assert started.wait(5)
            assert request(base, path, 'DELETE')[0] == 200
        finally:
            release.set()
            thread.join(5)
        assert results['r'][0] == 404
        assert request(base, path)[0] == 404
        assert request(base, '/chats')[1] == []


def test_two_concurrent_questions_keep_pairs_ordered(tmp_path):
    gate = threading.Event()
    entered = threading.Semaphore(0)

    def answer(context):
        entered.release()
        assert gate.wait(5)
        return {'status': 'abstain', 'explanation': context['question'], 'evidence': []}
    with running(tmp_path, answer) as base:
        _, path = setup_chat(base)
        results = {}
        threads = [ask_in_thread(base, path, results, 'a'), ask_in_thread(base, path, results, 'b')]
        try:
            assert entered.acquire(timeout=5) and entered.acquire(timeout=5)
        finally:
            gate.set()
            for t in threads:
                t.join(5)
        assert results['a'][0] == results['b'][0] == 200
        roles = [m['role'] for m in request(base, path)[1]['messages']]
        assert roles == ['user', 'assistant', 'user', 'assistant']


def test_answerer_exception_keeps_documented_abstain(tmp_path):
    def answer(context):
        raise RuntimeError('boom secret')
    with running(tmp_path, answer) as base:
        _, path = setup_chat(base)
        status, message = request(base, path + '/questions', 'POST', {'question': 'Q?', 'drawing_ids': IDS[path]})
        assert status == 200
        assert 'boom' not in str(message)
        assert message['answer']['status'] == 'abstain'
        assert message['answer']['error'] == 'analysis_error'


def test_unexpected_route_exception_returns_json_500(tmp_path, monkeypatch, capsys):
    def explode(*args, **kwargs):
        raise RuntimeError('secret internals')
    monkeypatch.setattr(api, 'inspect_upload', explode)
    with running(tmp_path) as base:
        _, path = setup_chat_empty(base)
        status, body = request(base, path + '/uploads?filename=x.png', 'POST', png())
        assert status == 500
        assert body == {'error': 'Internal server error'}
        assert 'secret' not in str(body)
    assert 'secret internals' in capsys.readouterr().err


def setup_chat_empty(base):
    chat = request(base, '/chats', 'POST', {})[1]
    return chat['id'], '/chats/' + chat['id']
