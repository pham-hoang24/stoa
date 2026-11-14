"""Uploaded IFC query scope and local execution, independent of dataset answers."""
import pytest
from stoa_chat.analysis import HybridAnswerer
from stoa.lanes import llm


def source(tmp_path, doors=2, clutter=0):
    import ifcopenshell
    m=ifcopenshell.file(schema='IFC4')
    m.create_entity('IfcProject',GlobalId=ifcopenshell.guid.new(),Name='Duplex Apartment - architectural')
    for i in range(doors):m.create_entity('IfcDoor',GlobalId=ifcopenshell.guid.new(),Name=f'Door {i}')
    for i in range(clutter):m.create_entity('IfcBuildingElementProxy',GlobalId=ifcopenshell.guid.new(),Name=f'Other {i}')
    path=tmp_path/'source.ifc';path.write_text(m.to_string())
    return {'id':'drawing','filename':'uploaded.ifc','format':'ifc','path':path,'sha256':'sha',
            'asset_url':'/asset','pages':[],'entity_ids':[e.GlobalId for e in m.by_type('IfcObject')]}


def ask(drawing,question):
    return HybridAnswerer()({'question':question,'drawing_ids':['drawing'],'drawings':[drawing],'messages':[]})


@pytest.mark.parametrize('question',[
    "How many doors are there in the model 'Duplex Apartment - architectural'?",
    'Could you please tell me the total number of doors in this uploaded model?',
    'Count all the doors in the model “Duplex Apartment - architectural”.'])
def test_named_model_counts_stay_local_and_ignore_unrelated_inventory(tmp_path,monkeypatch,question):
    d=source(tmp_path,clutter=2600)
    monkeypatch.setattr(llm,'chat',lambda *a,**k:pytest.fail('native count contacted provider'))
    # Even the selected doors must not load their unrelated property dictionaries for a count.
    monkeypatch.setattr('ifcopenshell.util.element.get_psets',lambda *a,**k:pytest.fail('count read properties'))
    answer=ask(d,question)
    assert answer['value']==2 and answer['status']=='supported'
    assert len(answer['evidence'])==2
    assert answer['native_query']['entity_type']=='IfcDoor'
    assert answer['native_query']['matched_entities']==2


def test_wrong_model_name_is_not_silently_ignored(tmp_path,monkeypatch):
    d=source(tmp_path)
    monkeypatch.setattr(llm,'chat',lambda *a,**k:pytest.fail('mismatched scope contacted provider'))
    answer=ask(d,"How many doors are in the model 'Another Building'?")
    assert answer['status']=='clarification' and answer['value'] is None
    assert 'Another Building' in answer['explanation']


def test_absent_ifc_class_does_not_claim_no_physical_doors(tmp_path,monkeypatch):
    d=source(tmp_path,doors=0,clutter=1)
    monkeypatch.setattr(llm,'chat',lambda *a,**k:pytest.fail('zero type count contacted provider'))
    answer=ask(d,'How many doors are there in the model?')
    assert answer['status']=='abstain' and answer['value'] is None
    assert answer['native_query']['matched_entities']==0
    assert 'IfcDoor' in answer['explanation']


def test_semantic_selection_receives_only_requested_type(tmp_path,monkeypatch):
    import json
    d=source(tmp_path,clutter=2600)
    def select(messages,**kw):
        p=json.loads(messages[1]['content'][0]['text'])
        assert all('Other' not in f.get('label','') for f in p['facts'])
        objects=[f for f in p['facts'] if f['kind']=='object']
        assert len(objects)==2
        return json.dumps({'operation':'count','complete':True,'coverage':p['required_coverage'],
                           'facts':[{'ref':objects[0]['id']}]})
    monkeypatch.setattr(llm,'chat',select)
    answer=ask(d,'How many exterior doors are in this model?')
    assert answer['status']=='proposal' and answer['value']==1
    assert answer['native_query']['matched_entities']==2


def test_subtypes_count_occurrences_and_exclude_type_definitions(tmp_path,monkeypatch):
    import ifcopenshell
    d=source(tmp_path,doors=0)
    m=ifcopenshell.open(str(d['path']))
    m.create_entity('IfcWallStandardCase',GlobalId=ifcopenshell.guid.new(),Name='Wall')
    m.create_entity('IfcWallType',GlobalId=ifcopenshell.guid.new(),Name='Definition')
    d['entity_ids']=[e.GlobalId for e in m.by_type('IfcObject')];d['path'].write_text(m.to_string())
    monkeypatch.setattr(llm,'chat',lambda *a,**k:pytest.fail('typed query contacted provider'))
    assert ask(d,'Count all walls in this model')['value']==1


def test_unknown_large_query_asks_for_type_before_reading_properties(tmp_path,monkeypatch):
    d=source(tmp_path,clutter=2600)
    monkeypatch.setattr('ifcopenshell.util.element.get_psets',lambda *a,**k:pytest.fail('unfiltered property dump'))
    answer=ask(d,'Tell me everything about the construction')
    assert answer['status']=='clarification' and answer['value'] is None


def test_named_model_does_not_change_target_from_title_words(tmp_path,monkeypatch):
    import ifcopenshell
    d=source(tmp_path)
    m=ifcopenshell.open(str(d['path']))
    m.by_type('IfcProject')[0].Name='Walls and Windows'
    d['path'].write_text(m.to_string())
    monkeypatch.setattr(llm,'chat',lambda *a,**k:pytest.fail('model title became target'))
    answer=ask(d,"How many doors in the model 'Walls and Windows'?")
    assert answer['value']==2 and answer['native_query']['entity_type']=='IfcDoor'


@pytest.mark.parametrize('question',["How many doors in the model Another Building?",'How many exterior doors in the model?'])
def test_unquoted_scope_and_empty_filtered_inventory_are_not_guessed(tmp_path,monkeypatch,question):
    d=source(tmp_path,doors=0)
    monkeypatch.setattr(llm,'chat',lambda *a,**k:pytest.fail('ambiguous/absent scope contacted provider'))
    answer=ask(d,question)
    assert answer['value'] is None and answer['status'] in {'clarification','abstain'}


def test_missing_global_id_cannot_silently_reduce_count(tmp_path,monkeypatch):
    import ifcopenshell
    d=source(tmp_path)
    m=ifcopenshell.open(str(d['path']))
    m.create_entity('IfcDoor',Name='Door without handle')
    d['path'].write_text(m.to_string())
    monkeypatch.setattr(llm,'chat',lambda *a,**k:pytest.fail('missing handle contacted provider'))
    answer=ask(d,'How many doors?')
    assert answer['value'] is None and answer['error']=='ifc_missing_identifiers'
    assert answer['native_query']['matched_entities']==3


def test_building_title_in_multi_project_upload_cannot_select_whole_file(tmp_path,monkeypatch):
    import ifcopenshell
    d=source(tmp_path)
    m=ifcopenshell.open(str(d['path']))
    m.create_entity('IfcProject',GlobalId=ifcopenshell.guid.new(),Name='Another Project')
    m.create_entity('IfcBuilding',GlobalId=ifcopenshell.guid.new(),Name='Named Building')
    d['path'].write_text(m.to_string())
    monkeypatch.setattr(llm,'chat',lambda *a,**k:pytest.fail('ambiguous scope contacted provider'))
    assert ask(d,"Count doors in the model 'Named Building'")['status']=='clarification'
