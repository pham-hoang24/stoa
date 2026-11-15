"""Original-resolution detail, exhaustive count coverage and source-frame evidence."""
import json
import cv2
import numpy as np
import pytest
from stoa_chat.analysis import HybridAnswerer
from stoa_chat import render
from stoa.lanes import llm


def drawing(tmp_path,width=3200,height=800):
    image=np.full((height,width,3),255,np.uint8)
    image[-1,-1]=[7,33,149]
    path=tmp_path/'plan.png';path.write_bytes(cv2.imencode('.png',image)[1].tobytes())
    return {'id':'drawing','filename':'plan.png','path':path,'format':'png','sha256':'hash',
            'asset_url':'/api/chats/chat/assets/drawing','pages':[{'page':1,'width':width,'height':height,'units':'px'}],'entity_ids':[]}


def context(d):return {'question':'How many bedrooms marked mh?','drawing_ids':[d['id']],'drawings':[d],'messages':[]}


def test_detail_views_preserve_pixels_and_ownership_covers_source_once(tmp_path):
    d=drawing(tmp_path)
    views=render.raster_views(d)
    assert views[0][1]['role']=='overview' and views[0][1]['width']==1600
    tiles=views[1:]
    assert len(tiles)==3
    area=0
    for data,v in tiles:
        pixels=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
        assert pixels.shape[1]==v['width']<=1400
        assert v['transform'][:4]==[1,0,0,1]
        x0,y0,x1,y1=v['core_bbox'];area+=(x1-x0)*(y1-y0)
    assert area==3200*800
    last=cv2.imdecode(np.frombuffer(tiles[-1][0],np.uint8),cv2.IMREAD_COLOR)
    assert last[-1,-1].tolist()==[7,33,149]
    assert tiles[-1][1]['source_bbox'][2:]==[3200,800]


def test_small_upload_is_one_original_resolution_view(tmp_path):
    views=render.raster_views(drawing(tmp_path,800,600))
    assert len(views)==1 and views[0][1]['width']==800


def test_large_count_visits_all_tiles_and_maps_labels_to_original(tmp_path,monkeypatch):
    d=drawing(tmp_path,7000,600)
    seen=[]
    def respond(messages,**kw):
        p=json.loads(messages[1]['content'][0]['text']);seen.extend(p['required_coverage'])
        assert sum(c['type']=='image_url' for c in messages[1]['content'])<=4 # overview + at most three tiles
        facts=[]
        for v in p['pages']:
            if v.get('role')!='detail':continue
            cx0,cy0,cx1,cy1=v['core_bbox']
            x=(cx0+cx1)/2;y=100
            facts.append({'page_ref':v['id'],'bbox':[x-5,y-5,x+5,y+5],
                          'kind':'text','printed_text':'mh','label':'bedroom'})
        return llm.Completion(json.dumps({'operation':'count','complete':True,'coverage':p['required_coverage'],'facts':facts}),{'provider':'nvidia' if len(seen)<=3 else 'modal'},'controlled')
    monkeypatch.setattr(llm,'chat',respond)
    answer=HybridAnswerer()(context(d))
    assert answer['status']=='proposal' and answer['value']==6
    assert len(seen)==len(set(seen))==6
    assert answer['image_processing']['completed_views']==answer['image_processing']['required_views']
    assert len(answer['model_provenance']['per_batch'])==2
    assert answer['model_provenance']['provider']=='mixed'
    assert answer['model_provenance']['per_batch'][1]['provider']=='modal'
    assert len(answer['evidence'])==6
    assert all(e['source_width']==7000 for e in answer['evidence'])
    assert max(e['bbox'][0] for e in answer['evidence'])>6000


def test_missing_tile_coverage_cannot_yield_total(tmp_path,monkeypatch):
    d=drawing(tmp_path)
    def bad(messages,**kw):
        p=json.loads(messages[1]['content'][0]['text'])
        return json.dumps({'operation':'count','complete':True,'coverage':p['required_coverage'][:-1],'facts':[]})
    monkeypatch.setattr(llm,'chat',bad)
    answer=HybridAnswerer()(context(d))
    assert answer['status']=='abstain' and answer['value'] is None
    assert answer['image_processing']['completed_views']==[]


def test_overview_cannot_supply_second_count(tmp_path,monkeypatch):
    d=drawing(tmp_path)
    def bad(messages,**kw):
        p=json.loads(messages[1]['content'][0]['text'])
        return json.dumps({'operation':'count','complete':True,'coverage':p['required_coverage'],
                           'facts':[{'page_ref':p['pages'][0]['id'],'bbox':[1,1,10,10],'kind':'object','label':'door'}]})
    monkeypatch.setattr(llm,'chat',bad)
    answer=HybridAnswerer()(context(d))
    assert answer['status']=='abstain' and answer['value'] is None


def test_measuring_with_overview_boundary_and_detail_scale_uses_source_frame():
    from stoa_chat.extraction import calculate
    base={'drawing_id':'d','page':1,'source_width':3200,'source_height':800,'source_origin':[0,0]}
    overview={**base,'id':'d:1','role':'overview','width':1600,'height':400,'transform':[2,0,0,2,0,0]}
    detail={**base,'id':'d:1:tile:0:0','role':'detail','width':1400,'height':800,'transform':[1,0,0,1,0,0],
            'source_bbox':[0,0,1400,800],'core_bbox':[0,0,1260,800]}
    plan={'operation':'polygon_area','complete':True,'coverage':[detail['id']],'facts':[
        {'page_ref':overview['id'],'bbox':[0,0,100,100],'kind':'boundary','polygon':[[0,0],[100,0],[100,100],[0,100]]},
        {'page_ref':detail['id'],'bbox':[10,10,120,30],'kind':'scale','value':1,'unit':'m','printed_text':'1 m',
         'dimension_line':[[10,20],[110,20]]}]}
    answer=calculate(plan,{p['id']:p for p in [overview,detail]},{},'area',[],[detail['id']])
    assert answer['value']==pytest.approx(4)


def test_near_identical_overlap_is_deduplicated_but_disagreement_abstains():
    from stoa_chat.image_analysis import merge_counts
    def answer(view,box,label='mh'):
        return {'calculation':{'count_basis':'text_markers','facts':[{'kind':'text','printed_text':label}]},
                'evidence':[{'drawing_id':'d','page':1,'view_id':view,'bbox':box}]}
    first=answer('a',[100,100,120,120])
    facts,ev,duplicates,_=merge_counts([first,answer('b',[100.5,100,120.5,120])])
    assert len(facts)==len(ev)==1 and duplicates==1
    assert len(merge_counts([first,answer('b',[200,100,220,120])])[0])==2
    with pytest.raises(ValueError,match='disagree'):merge_counts([first,answer('b',[100,100,120,120],'kitchen')])


def test_count_regions_must_belong_to_core_and_cannot_be_clipped():
    from stoa_chat.extraction import count_region
    p={'role':'detail','width':1400,'height':800,'source_bbox':[1120,0,2520,800],
       'source_origin':[0,0],'source_width':3200,'source_height':800,'core_bbox':[140,0,1260,800]}
    with pytest.raises(ValueError,match='ownership'):count_region({'bbox':[10,10,30,30]},p)
    with pytest.raises(ValueError,match='clipped'):count_region({'bbox':[1000,10,1400,30]},p)


def test_later_batch_cap_never_returns_partial_count(tmp_path,monkeypatch):
    d=drawing(tmp_path,7000,600);calls=[]
    def respond(messages,**kw):
        calls.append(1)
        if len(calls)>1:raise llm.LLMError('request cap reached')
        p=json.loads(messages[1]['content'][0]['text'])
        return json.dumps({'operation':'count','complete':True,'coverage':p['required_coverage'],'facts':[]})
    monkeypatch.setattr(llm,'chat',respond)
    answer=HybridAnswerer()(context(d))
    assert answer['value'] is None and answer['error']=='provider_unavailable'
    assert len(answer['image_processing']['completed_views'])==3
    assert len(answer['image_processing']['required_views'])==6
    assert answer['model_provenance']['per_batch'][1]['status']=='abstain'


def test_reconciliation_budget_never_truncates_into_count(monkeypatch):
    from stoa_chat import image_analysis
    monkeypatch.setattr(image_analysis,'MAX_COUNT_FACTS',1)
    a={'calculation':{'facts':[{},{}]}}
    with pytest.raises(ValueError,match='budget'):image_analysis.merge_counts([a])


@pytest.mark.parametrize('kind,operation,values,expected',[
    ('length','sum',[2],2),('area','product',[2,3],6),
    ('volume','product',[2,3,4],24),('text','text',[], 'Kitchen')])
def test_large_non_count_questions_use_one_full_view(tmp_path,monkeypatch,kind,operation,values,expected):
    """Non-count questions no longer tile (tiling exhausted the model's budget); one view, source-frame boxes."""
    d=drawing(tmp_path)
    def respond(messages,**kw):
        p=json.loads(messages[1]['content'][0]['text'])
        assert sum(c['type']=='image_url' for c in messages[1]['content'])==1
        assert len(p['pages'])==1 and p['pages'][0].get('role') is None
        v=p['pages'][0]
        assert v['width']==render.SINGLE_VIEW_MAX_SIDE
        facts=[{'page_ref':v['id'],'bbox':[20+i*30,50,40+i*30,70],'kind':'length',
                'value':value,'unit':'m','printed_text':f'{value} m'} for i,value in enumerate(values)]
        if kind=='text':facts=[{'page_ref':v['id'],'bbox':[20,50,100,70],'kind':'text','value':'Kitchen'}]
        return json.dumps({'operation':operation,'complete':True,'facts':facts})
    monkeypatch.setattr(llm,'chat',respond)
    c=context(d);c['question']='What is the '+kind+'?'
    answer=HybridAnswerer()(c)
    assert answer['status']=='proposal' and answer['value']==expected
    assert answer['evidence'][0]['bbox'][0]==pytest.approx(20*3200/3000)
