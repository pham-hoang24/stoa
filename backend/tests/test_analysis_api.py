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
    assignment=f.create_entity('IfcUnitAssignment', Units=[f.create_entity('IfcSIUnit',UnitType=t,Name=n) for t,n in [('LENGTHUNIT','METRE'),('AREAUNIT','SQUARE_METRE'),('VOLUMEUNIT','CUBIC_METRE')]])
    f.create_entity('IfcProject', GlobalId=ifcopenshell.guid.new(), Name='Studio',UnitsInContext=assignment)
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


def test_native_dxf_geometry_uses_declared_units_and_unknown_units_abstains(tmp_path, monkeypatch):
    import ezdxf
    from stoa.lanes import llm
    monkeypatch.setattr(llm, 'chat', lambda *a, **k: (_ for _ in ()).throw(llm.LLMError('no API key')))
    with running(tmp_path) as base:
        for units, expected in [(4, 5), (0, None)]:
            dxf = ezdxf.new()
            dxf.header['$INSUNITS'] = units
            dxf.modelspace().add_line((0,0), (3000,4000))
            stream = io.StringIO()
            dxf.write(stream)
            path, drawing = upload(base, 'arbitrary.dxf', stream.getvalue().encode())
            answer = ask(base, path, drawing, 'What is the total length of lines?')
            assert answer['value'] == expected
            if expected:
                assert answer['evidence'][0]['entity_handle'] in drawing['entity_ids']
                assert answer['unit'] == 'm'
            else:
                assert answer['status'] == 'abstain'


def test_native_pdf_text_and_safe_svg_geometry_are_inspectable_without_provider(tmp_path, monkeypatch):
    import pymupdf
    from stoa.lanes import llm
    monkeypatch.setattr(llm, 'chat', lambda *a, **k: (_ for _ in ()).throw(llm.LLMError('no API key')))
    pdf = pymupdf.open()
    pdf.new_page(width=200,height=200).insert_text((20,40),'Sauna 12 m2')
    with running(tmp_path) as base:
        path, drawing = upload(base, 'unseen.pdf', pdf.tobytes())
        text = ask(base, path, drawing, 'What text is on this drawing?')
        assert text['value'] == 'Sauna 12 m2'
        assert text['status'] == 'supported'
        assert text['evidence'][0]['bbox'][0] == 20
        assert request(base, text['evidence'][0]['preview_url'].removeprefix('/api'))[0] == 200
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="6000mm" height="4000mm" data-metres-per-unit="1" viewBox="10 20 6 4"><rect id="outline" x="10" y="20" width="6" height="4"/></svg>'
        path, drawing = upload(base, 'unseen.svg', svg)
        area = ask(base, path, drawing, 'What is the total area of rectangles?')
        assert area['value'] == 24
        assert area['evidence'][0]['entity_id'] == 'outline'
        assert area['unit'] == 'm²'
        preview = request(base, area['evidence'][0]['preview_url'].removeprefix('/api'))
        assert preview[0] == 200 and preview[1].startswith(b'\x89PNG')


def test_visual_dimensions_compute_area_volume_length_and_text_with_evidence(tmp_path, monkeypatch):
    from stoa.lanes import llm
    plans = [
        ('What is the area of the sauna?', 'product', [('length',3,'m'),('length',400,'cm')], 12, 'm²'),
        ('What is the volume of the sauna?', 'product', [('length',3,'m'),('length',4,'m'),('length',2.5,'m')], 30, 'm³'),
        ('What is the length of the bench?', 'sum', [('length',2500,'mm')], 2.5, 'm'),
        ('What label is shown?', 'text', [('text','SAUNA',None)], 'SAUNA', None),
    ]
    current = []
    def extract(messages, **kwargs):
        payload = json.loads(messages[-1]['content'][0]['text'])
        operation, values = current[0]
        return json.dumps({'operation':operation,'complete':True,'estimate':True,
                           'facts':[{'page_ref':payload['pages'][0]['id'],'bbox':[i*4,0,i*4+3,3],
                                     'kind':k,'value':v,'unit':u,'printed_text':f'{v} {u}'} for i,(k,v,u) in enumerate(values)]})
    monkeypatch.setattr(llm, 'chat', extract)
    with running(tmp_path) as base:
        path, drawing = upload(base, 'plan.png', png())
        for question,operation,values,expected,unit in plans:
            current[:] = [(operation,values)]
            answer = ask(base,path,drawing,question)
            assert answer['value'] == expected, answer
            assert answer['unit'] == unit
            assert answer['status'] == 'estimate' and answer['review_status'] == 'unreviewed'
            assert answer['calculation']['operation'] == operation


def test_visual_boundaries_need_calibration_and_volume_needs_height(tmp_path, monkeypatch):
    from stoa.lanes import llm
    plan = {}
    def extract(messages, **kwargs):
        payload = json.loads(messages[-1]['content'][0]['text'])
        ref = payload['pages'][0]['id']
        return json.dumps({**plan, 'complete':True, 'facts':[{**f,'page_ref':ref} for f in plan['facts']]})
    monkeypatch.setattr(llm,'chat',extract)
    boundary = {'kind':'boundary','bbox':[0,0,12,10],'polygon':[[0,0],[12,0],[12,10],[0,10]]}
    calibration = {'kind':'scale','bbox':[1,1,3,3],'value':.5,'unit':'m/pixel','printed_text':'0.5 m/pixel'}
    with running(tmp_path) as base:
        path,drawing = upload(base,'plan.png',png())
        plan.update(operation='polygon_area',facts=[boundary,calibration])
        answer = ask(base,path,drawing,'What is the area of the sauna?')
        assert answer['value'] == 30, answer
        assert answer['evidence'][0]['polygon'] == boundary['polygon']
        plan.update(facts=[boundary])
        assert ask(base,path,drawing,'What is the area?')['status'] == 'abstain'
        plan.update(operation='product', facts=[{'kind':'length','bbox':[0,0,2,2],'value':3,'unit':'m','printed_text':'3 m'},
                                                {'kind':'length','bbox':[4,0,6,2],'value':4,'unit':'m','printed_text':'4 m'}])
        assert ask(base,path,drawing,'What is the volume?')['status'] == 'abstain'


def test_invalid_extractions_and_provider_outage_never_become_numbers(tmp_path, monkeypatch):
    from stoa.lanes import llm
    current = {}
    def extract(messages, **kwargs):
        payload = json.loads(messages[-1]['content'][0]['text'])
        p = payload['pages'][0]['id']
        return json.dumps({'operation':'count','complete':True,'coverage':[p],
                           'facts':[{**current,'page_ref':p}]})
    monkeypatch.setattr(llm,'chat',extract)
    with running(tmp_path) as base:
        path,drawing = upload(base,'plan.png',png())
        for bad in [{'kind':'object','bbox':[-1,0,2,2]}, {'kind':'object','bbox':[0,0,99,99]},
                    {'ref':'invented-native-entity'}, {'kind':'object','bbox':[0,0,2,2],'polygon':[[0,0],[99,0],[1,1]]}]:
            current.clear();current.update(bad)
            answer = ask(base,path,drawing,'How many sinks?')
            assert answer['status']=='abstain' and answer['value'] is None
        monkeypatch.setattr(llm,'chat',lambda *a,**k: (_ for _ in ()).throw(llm.LLMError('request cap reached (0 live requests)')))
        outage = ask(base,path,drawing,'How many sinks?')
        assert outage['error']=='provider_unavailable' and 'cap' in outage['explanation']


def test_native_model_selection_cannot_promote_unreviewed_interpretation(tmp_path, monkeypatch):
    from stoa.lanes import llm
    def extract(messages,**kwargs):
        payload = json.loads(messages[-1]['content'][0]['text'])
        facts = [f for f in payload['facts'] if f['kind']=='area']
        return json.dumps({'operation':'sum','complete':True,'facts':[{'ref':f['id']} for f in facts]})
    monkeypatch.setattr(llm,'chat',extract)
    with running(tmp_path) as base:
        path,drawing = upload(base,'native.ifc',model())
        answer = ask(base,path,drawing,'What is the area of north-facing walls?')
        assert answer['status']=='proposal' and answer['review_status']=='unreviewed'
        assert answer['value']==12
        assert all(e['property']=='Qto_WallBaseQuantities.NetSideArea' for e in answer['evidence'])


def test_multidrawing_confirmation_contributions_and_duplicate_clarification(tmp_path, monkeypatch):
    from stoa.lanes import llm
    monkeypatch.setattr(llm,'chat',lambda *a,**k: (_ for _ in ()).throw(llm.LLMError('no API key')))
    with running(tmp_path) as base:
        path,a = upload(base,'one.ifc',model())
        _,b = upload(base,'two.ifc',model(),path)
        _,duplicate = upload(base,'renamed.ifc',request(base,path+'/assets/'+a['id'])[1],path)
        def multi(question,ids):
            return request(base,path+'/questions','POST',{'question':question,'drawing_ids':ids})[1]['answer']
        assert multi('How many walls?',[a['id'],b['id']])['status']=='clarification'
        total = multi('Yes, these drawings are independent.',[a['id'],b['id']])
        assert total['value']==4,total
        assert [c['value'] for c in total['contributions']]==[2,2]
        assert len(total['evidence'])==4
        assert multi('These are independent. How many walls?',[a['id'],duplicate['id']])['status']=='clarification'
        assert multi('What is their total area?',[b['id']])['status']=='clarification'


def test_sheet_units_and_missing_ifc_units_do_not_invent_building_scale(tmp_path, monkeypatch):
    import ifcopenshell
    from stoa.lanes import llm
    monkeypatch.setattr(llm,'chat',lambda *a,**k: (_ for _ in ()).throw(llm.LLMError('no API key')))
    with running(tmp_path) as base:
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="6000mm" height="4000mm" viewBox="0 0 6 4"><rect id="outline" width="6" height="4"/></svg>'
        path,drawing=upload(base,'sheet.svg',svg)
        assert ask(base,path,drawing,'What is the area of rectangles?')['status']=='abstain'
        no_units = ifcopenshell.file.from_string(model().decode())
        project = no_units.by_type('IfcProject')[0]
        project.UnitsInContext = None
        path,drawing=upload(base,'no-units.ifc',no_units.to_string().encode())
        assert ask(base,path,drawing,'What is the area of walls?')['status']=='abstain'


def test_exif_jpeg_uses_raw_pixel_frame_and_zero_has_coverage(tmp_path, monkeypatch):
    import struct
    import cv2
    import numpy as np
    from stoa.lanes import llm
    content=cv2.imencode('.jpg',np.zeros((12,16,3),dtype=np.uint8))[1].tobytes()
    exif=b'Exif\0\0II'+struct.pack('<HIH',42,8,1)+struct.pack('<HHI',0x112,3,1)+struct.pack('<H',6)+b'\0\0'+struct.pack('<I',0)
    content=content[:2]+b'\xff\xe1'+struct.pack('>H',len(exif)+2)+exif+content[2:]
    def extract(messages,**kwargs):
        payload=json.loads(messages[-1]['content'][0]['text'])
        page=payload['pages'][0]
        assert [page['width'],page['height']]==[16,12]
        return json.dumps({'operation':'count','complete':True,'coverage':[page['id']],'facts':[]})
    monkeypatch.setattr(llm,'chat',extract)
    with running(tmp_path) as base:
        path,drawing=upload(base,'rotated.jpg',content)
        answer=ask(base,path,drawing,'How many saunas?')
        assert answer['value']==0,answer
        assert answer['evidence'][0]['coverage']
        assert answer['evidence'][0]['source_sha256']==drawing['sha256']


def test_ifc_subtypes_typed_quantities_override_units_and_length_roles(tmp_path, monkeypatch):
    import ifcopenshell
    from stoa.lanes import llm
    monkeypatch.setattr(llm,'chat',lambda *a,**k: (_ for _ in ()).throw(llm.LLMError('no API key')))
    f=ifcopenshell.file.from_string(model().decode())
    wall=f.by_type('IfcWall')[0]
    wall=f.create_entity('IfcWallStandardCase',GlobalId=wall.GlobalId,Name='Subtype')
    # Keep only subtype wall with a Height quantity: no source Length is present.
    for other in list(f.by_type('IfcWall')):
        if other!=wall:
            f.remove(other)
    height=f.create_entity('IfcQuantityLength',Name='Height',LengthValue=3.)
    area_unit=f.create_entity('IfcSIUnit',UnitType='AREAUNIT',Prefix='MILLI',Name='SQUARE_METRE')
    area=f.create_entity('IfcQuantityArea',Name='NetSideArea',AreaValue=6000000.,Unit=area_unit)
    qto=f.create_entity('IfcElementQuantity',GlobalId=ifcopenshell.guid.new(),Name='Qto_WallBaseQuantities',Quantities=[height,area])
    f.create_entity('IfcRelDefinesByProperties',GlobalId=ifcopenshell.guid.new(),RelatedObjects=[wall],RelatingPropertyDefinition=qto)
    with running(tmp_path) as base:
        path,drawing=upload(base,'subtype.ifc',f.to_string().encode())
        assert ask(base,path,drawing,'How many walls?')['value']==1
        assert ask(base,path,drawing,'What is the total length of walls?')['status']=='abstain'
        assert ask(base,path,drawing,'What is the total area of walls?')['value']==6


def test_negated_independence_and_nonadditive_questions_cannot_produce_total(tmp_path):
    with running(tmp_path) as base:
        path,a=upload(base,'a.ifc',model())
        _,b=upload(base,'b.ifc',model(),path)
        for question in ['They are not independent. How many walls?', 'Compare the number of walls.', 'What is the difference in wall area?']:
            answer=request(base,path+'/questions','POST',{'question':question,'drawing_ids':[a['id'],b['id']]})[1]['answer']
            assert answer['status']=='clarification' and answer['value'] is None


def test_model_native_object_count_uses_real_handles_and_full_source_coverage(tmp_path,monkeypatch):
    import ezdxf
    from stoa.lanes import llm
    dxf=ezdxf.new()
    dxf.modelspace().add_blockref('SINK',(0,0))
    stream=io.StringIO();dxf.write(stream)
    def extract(messages,**kwargs):
        payload=json.loads(messages[-1]['content'][0]['text'])
        facts=[f for f in payload['facts'] if f['kind']=='object']
        return json.dumps({'operation':'count','complete':True,'target':'sink','coverage':payload['required_coverage'],
                           'facts':[{'ref':f['id']} for f in facts]})
    monkeypatch.setattr(llm,'chat',extract)
    with running(tmp_path) as base:
        path,drawing=upload(base,'fixture.dxf',stream.getvalue().encode())
        answer=ask(base,path,drawing,'How many sinks?')
        assert answer['value']==1,answer
        assert answer['status']=='proposal'
        assert answer['evidence'][0]['entity_handle'] in drawing['entity_ids']
