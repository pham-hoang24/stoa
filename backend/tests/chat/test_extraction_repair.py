"""A bounded correction for invalid model evidence, without guessing coordinates."""
import json
import pytest
from stoa_chat.extraction import extract, calculate
from stoa.lanes import llm


@pytest.fixture
def source(monkeypatch):
    page={'id':'drawing:1','drawing_id':'drawing','page':1,'width':482,'height':507,
          'transform':[1,0,0,1,0,0]}
    drawing={'id':'drawing','pages':[{'page':1}],'entity_ids':[]}
    monkeypatch.setattr('stoa_chat.extraction.preview',lambda *a:(b'png',page))
    monkeypatch.setattr(llm,'image_part',lambda *a:{'type':'image_url','image_url':{'url':'controlled'}})
    return page,drawing,{'question':'How many kitchens including kitchenettes, open kitchens and utility kitchens?',
                        'drawing_ids':['drawing'],'drawings':[drawing],'messages':[]}


def kitchen(page,normalized=False):
    return {'operation':'count','complete':True,'coverage':[page['id']],
            'facts':[{'page_ref':page['id'],'bbox':[100,520,220,620],'kind':'text',
                      'printed_text':'Keittiö',**({'coordinate_space':'normalized_1000'} if normalized else {})}]}


def test_out_of_bounds_kitchen_requests_one_correction_and_keeps_actual_producer(source,monkeypatch):
    page,drawing,context=source
    calls=[]
    def respond(messages,**kw):
        calls.append(messages[:])
        if len(calls)==2:
            feedback=json.loads(messages[-1]['content'])
            assert 'outside' in feedback['validation_error']
            assert feedback['pages'][0]['width']==482
            assert feedback['pages'][0]['height']==507
        return llm.Completion(json.dumps(kitchen(page,normalized=len(calls)==2)),{'provider':'modal'},'controlled-model')
    monkeypatch.setattr(llm,'chat',respond)
    answer=extract(context,[{'objects':[],'facts':[],'complete':False}],'count')
    assert len(calls)==2 and answer['value']==1 and answer['status']=='proposal'
    assert answer['evidence'][0]['bbox']==pytest.approx([48.2,263.64,106.04,314.34])
    assert answer['model_provenance']['provider']=='modal'
    assert answer['model_provenance']['extraction_attempts']==2
    assert answer['review_status']=='unreviewed'


@pytest.mark.parametrize('response',['bounds','empty','malformed'])
def test_repeated_invalid_output_stops_with_specific_reason(source,monkeypatch,response):
    page,drawing,context=source
    calls=[]
    def bad(*a,**k):
        calls.append(1)
        return json.dumps(kitchen(page)) if response=='bounds' else '' if response=='empty' else '{'
    monkeypatch.setattr(llm,'chat',bad)
    answer=extract(context,[{'objects':[],'facts':[],'complete':False}],'count')
    assert len(calls)==2 and answer['status']=='abstain' and answer['value'] is None
    assert answer['error']=='invalid_extraction'
    assert ('outside' if response=='bounds' else 'empty' if response=='empty' else 'JSON') in answer['explanation']


def test_unmarked_out_of_bounds_is_not_guessed_or_clamped(source):
    page,drawing,_=source
    with pytest.raises(ValueError,match='outside'):
        calculate(kitchen(page),{page['id']:page},{},'count',[drawing],[page['id']])


def test_normalized_coordinates_require_known_units_and_bounds(source):
    page,drawing,_=source
    for space,box in [('unknown',[1,1,2,2]),('normalized_1000',[0,0,1001,500])]:
        p=kitchen(page,True);p['facts'][0].update(coordinate_space=space,bbox=box)
        with pytest.raises(ValueError):
            calculate(p,{page['id']:page},{},'count',[drawing],[page['id']])


def test_valid_and_deliberate_abstain_need_no_correction(source,monkeypatch):
    page,drawing,context=source
    calls=[]
    for p in [kitchen(page,True),{'operation':'abstain','missing':'Label illegible'}]:
        def respond(*a,**k):calls.append(1);return json.dumps(p)
        monkeypatch.setattr(llm,'chat',respond)
        answer=extract(context,[{'objects':[],'facts':[],'complete':False}],'count')
        assert answer['status']==('abstain' if p['operation']=='abstain' else 'proposal')
        assert answer['value']==(None if p['operation']=='abstain' else 1)
    assert len(calls)==2


def test_provider_failure_does_not_start_format_correction(source,monkeypatch):
    _,_,context=source
    calls=[]
    def unavailable(*a,**k):
        calls.append(1)
        raise llm.LLMError('request cap reached')
    monkeypatch.setattr(llm,'chat',unavailable)
    answer=extract(context,[{'objects':[],'facts':[],'complete':False}],'count')
    assert len(calls)==1 and answer['error']=='provider_unavailable'


def test_normalized_boundary_and_calibration_use_same_preview_frame(source):
    page,drawing,_=source
    base={'page_ref':page['id'],'coordinate_space':'normalized_1000','bbox':[0,0,1000,1000]}
    p={'operation':'polygon_area','complete':True,'facts':[
        {**base,'kind':'boundary','polygon':[[0,0],[1000,0],[1000,1000],[0,1000]]},
        {**base,'kind':'scale','value':10,'unit':'m','printed_text':'10 m','dimension_line':[[0,0],[1000,0]]}]}
    answer=calculate(p,{page['id']:page},{},'area',[drawing],[])
    assert answer['value']==pytest.approx(100*507/482)
    assert answer['evidence'][0]['polygon'][2]==[482,507]
    p['facts'][0]['polygon'][0].append(1)
    with pytest.raises(ValueError):calculate(p,{page['id']:page},{},'area',[drawing],[])


def test_correction_respects_request_cap(source,monkeypatch):
    page,_,context=source
    calls=[]
    def respond(*a,**k):
        calls.append(1)
        if len(calls)>1:raise llm.LLMError('request cap reached')
        return json.dumps(kitchen(page))
    monkeypatch.setattr(llm,'chat',respond)
    answer=extract(context,[{'objects':[],'facts':[],'complete':False}],'count')
    assert len(calls)==2 and answer['value'] is None
    assert answer['error']=='provider_unavailable' and 'cap' in answer['explanation']
