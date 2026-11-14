"""Count cited label occurrences without promoting them to verified objects."""
import json
import pytest
from stoa_chat.analysis import HybridAnswerer
from stoa_chat.extraction import calculate


@pytest.fixture
def page():
    return {'id':'drawing:1','drawing_id':'drawing','page':1,'width':500,'height':500,
            'transform':[1,0,0,1,0,0]}


def plan(page, label='mh'):
    return {'operation':'count','complete':True,'coverage':[page['id']],
            'target':'bedrooms marked as '+label,
            'facts':[{'page_ref':page['id'],'bbox':[x,10,x+20,30],
                      'kind':'text','label':label,'printed_text':label} for x in [10,50,90]]}


@pytest.mark.parametrize('label',['mh','BR','office'])
def test_label_count_preserves_transcriptions_and_review_status(tmp_path, monkeypatch, label):
    import cv2
    import numpy as np
    from stoa.lanes import llm
    source=tmp_path/'plan.png'
    source.write_bytes(cv2.imencode('.png',np.full((500,500,3),255,np.uint8))[1].tobytes())
    drawing={'id':'drawing','format':'png','path':source,'sha256':'sourcehash','asset_url':'/source',
             'pages':[{'page':1,'width':500,'height':500,'units':'px'}],'entity_ids':[]}
    monkeypatch.setattr(llm,'chat',lambda messages,**kw:json.dumps(plan(json.loads(messages[-1]['content'][0]['text'])['pages'][0],label)))
    answer=HybridAnswerer()({'question':'How many bedrooms marked '+label+'?',
                            'drawing_ids':['drawing'],'drawings':[drawing],'messages':[]})
    assert answer['status']=='proposal' and answer['value']==3
    assert answer['review_status']=='unreviewed'
    assert len(answer['evidence'])==3
    assert answer['calculation']['count_basis']=='text_markers'
    assert all(f['kind']=='text' and f['printed_text']==label for f in answer['calculation']['facts'])
    assert 'one marker per object' in answer['explanation']


@pytest.mark.parametrize('damage',['missing_text','blank_text','numeric_text','duplicate_region','bad_region','unknown_page','partial_coverage','mixed_object'])
def test_label_counts_still_require_transcriptions_distinct_regions_and_coverage(page,damage):
    p=plan(page)
    if damage=='missing_text': del p['facts'][0]['printed_text']
    if damage=='blank_text': p['facts'][0]['printed_text']='  '
    if damage=='numeric_text': p['facts'][0]['printed_text']=3
    if damage=='duplicate_region': p['facts'][1]['bbox']=p['facts'][0]['bbox']
    if damage=='bad_region': p['facts'][0]['bbox']=[0,0,999,999]
    if damage=='unknown_page': p['facts'][0]['page_ref']='other:1'
    if damage=='partial_coverage': p['coverage']=[]
    if damage=='mixed_object': p['facts'][0]['kind']='object'
    with pytest.raises(ValueError):
        calculate(p,{page['id']:page},{},'count',[],[page['id']])
