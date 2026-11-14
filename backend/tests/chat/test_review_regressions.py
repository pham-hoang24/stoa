"""Review regressions exercised through uploaded drawings and HTTP answers."""
import json
import pytest
from test_chat_api import running, request, png
from test_analysis_api import upload, ask


@pytest.mark.parametrize('presentation', ['style="visibility:hidden"', 'opacity="0"', 'fill="none" stroke="none"', 'style="fill-opacity:0"', 'visibility="hidden"'])
@pytest.mark.parametrize('question', ['How many rectangles?', 'What is the total area of rectangles?'])
def test_invisible_svg_geometry_is_not_native_evidence(tmp_path, monkeypatch, presentation, question):
    from stoa.lanes import llm
    def controlled(messages, **kwargs):
        payload = json.loads(messages[-1]['content'][0]['text'])
        assert not [f for f in payload['facts'] if f['kind'] in {'object', 'area', 'length'}]
        assert payload['scope'][0]['native_inventory_complete'] is False
        return json.dumps({'operation': 'abstain', 'missing': 'No visible requested shapes'})
    monkeypatch.setattr(llm, 'chat', controlled)
    with running(tmp_path) as base:
        content = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" data-metres-per-unit="1"><g {presentation}><rect id="hidden" width="4" height="5"/></g></svg>'.encode()
        path, drawing = upload(base, 'hidden.svg', content)
        assert ask(base, path, drawing, question)['status'] == 'abstain'


def test_same_sentence_independence_preserves_question_and_negation(tmp_path, monkeypatch):
    from stoa.lanes import llm
    seen = []
    def controlled(messages, **kwargs):
        payload = json.loads(messages[-1]['content'][0]['text'])
        seen.append(payload['question'])
        assert payload['kind'] == 'count'
        page = payload['pages'][0]
        return json.dumps({'operation':'count', 'complete':True, 'coverage':[page['id']], 'facts':[]})
    monkeypatch.setattr(llm, 'chat', controlled)
    with running(tmp_path) as base:
        path, a = upload(base, 'a.png', png())
        _, b = upload(base, 'b.svg', b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" style="opacity:1"/>', path)
        def multi(question):
            return request(base, path+'/questions', 'POST', {'question':question, 'drawing_ids':[a['id'], b['id']]})[1]['answer']
        answer = multi('These are independent, how many rectangles?')
        assert answer['value'] == 0
        assert seen == ['how many rectangles?', 'how many rectangles?']
        seen.clear()
        assert multi('These are not independent, how many rectangles?')['status'] == 'clarification'
        assert not seen


def test_answer_introduced_target_and_facts_survive_scoped_followup(tmp_path, monkeypatch):
    from stoa.lanes import llm
    calls = []
    def controlled(messages, **kwargs):
        payload = json.loads(messages[-1]['content'][0]['text'])
        calls.append(payload)
        page = payload['pages'][0]
        if payload['question'].startswith('Which'):
            return json.dumps({'operation':'text','complete':True,'target':'Sauna A', 'facts':[
                {'kind':'text','value':'Sauna A','page_ref':page['id'],'bbox':[0,0,3,3]}]})
        previous = payload['prior_answers'][-1]
        assert previous['target'] == 'Sauna A'
        assert previous['value'] == 'Sauna A'
        assert previous['review_status'] == 'unreviewed'
        assert previous['facts'][0]['value'] == 'Sauna A'
        assert previous['drawing_ids'] == [page['drawing_id']]
        assert 'evidence' not in previous
        return json.dumps({'operation':'sum','complete':True,'target':'Sauna A', 'facts':[
            {'kind':'length','value':8,'unit':'m','printed_text':'8 m','page_ref':page['id'],'bbox':[3,3,8,8]}]})
    monkeypatch.setattr(llm,'chat',controlled)
    with running(tmp_path) as base:
        path, a = upload(base,'a.png',png())
        assert ask(base,path,a,'Which room is largest?')['value'] == 'Sauna A'
    with running(tmp_path) as base:
        answer = ask(base,path,a,'What is its perimeter?')
        assert answer['value'] == 8
        assert answer['review_status'] == 'unreviewed'
        _, b = upload(base,'b.png',png(),path)
        assert ask(base,path,b,'What is its perimeter?')['status'] == 'clarification'
        assert len(calls) == 2
