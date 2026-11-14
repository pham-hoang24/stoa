"""IFC scope and inventory contracts through the public router/CLI boundary."""
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.unit
import pytest

from stoa import cli, data
from stoa.data import Question
from stoa.lanes import ifc, llm
from stoa.router import answer


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("IFC inventory questions must not fall back to an LLM")
    monkeypatch.setattr(llm, "answer", unexpected)


@pytest.fixture
def model(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    folder = tmp_path / "data" / "ifc_models"
    folder.mkdir(parents=True)
    f = ifcopenshell.file(schema="IFC4")
    f.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Test model")
    units = [ifcopenshell.api.unit.add_si_unit(f, unit_type=k, prefix=p)
             for k, p in [("LENGTHUNIT", "MILLI"), ("AREAUNIT", None), ("VOLUMEUNIT", None)]]
    ifcopenshell.api.unit.assign_unit(f, units=units)
    storey = f.create_entity("IfcBuildingStorey", GlobalId=ifcopenshell.guid.new(), Name="Ground")

    def element(cls="IfcWall", name="Wall", quantities=None, level=storey):
        e = f.create_entity(cls, GlobalId=ifcopenshell.guid.new(), Name=name)
        if level is not None:
            f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                            RelatedElements=[e], RelatingStructure=level)
        if quantities:
            qs = []
            for key, value in quantities.items():
                kind = "Length" if key == "Length" else "Volume" if "Volume" in key else "Area"
                qs.append(f.create_entity(f"IfcQuantity{kind}", Name=key, **{f"{kind}Value": value}))
            qto = f.create_entity("IfcElementQuantity", GlobalId=ifcopenshell.guid.new(),
                                  Name="BaseQuantities", Quantities=qs)
            f.create_entity("IfcRelDefinesByProperties", GlobalId=ifcopenshell.guid.new(),
                            RelatedObjects=[e], RelatingPropertyDefinition=qto)
        return e

    def save(stem="test"):
        path = folder / f"{stem}.ifc"
        f.write(str(path))
        ifc._open.cache_clear()
        return f"data/ifc_models/{path.name}"

    return f, storey, element, save, folder


def ask(path, text):
    return answer(Question(path=path, question=text))


@pytest.mark.parametrize("ext", ["ifc", "pdf", "svg"])
def test_whole_model_keeps_every_global_id_through_cli(model, ext):
    f, storey, element, save, folder = model
    expected = {element().GlobalId for _ in range(251)}
    expected.add(element(name="Uncontained", level=None).GlobalId)
    save()
    path = "data/ifc_models/test.ifc" if ext == "ifc" else f"data/ifc_models/test_plan-01-ground.{ext}"
    if ext != "ifc":
        (folder / Path(path).name).write_text("displayed floor is only a partial view")
    result = cli.ask(path, "How many walls are there in the model 'Test model'?")
    assert result["value"] == 252 and result["unit"] == "count"
    assert {e["global_id"] for e in result["evidence"]} == expected
    assert len(result["evidence"]) == len(expected)
    assert all(e["file"].endswith("test.ifc") for e in result["evidence"])
    assert all("scope=model:" in e["label"] and "method=IFC element inventory" in e["label"]
               for e in result["evidence"])
    floor = ask(path, "How many walls are shown on the floor plan of 'Ground'?")
    assert floor.value == 251 and len(floor.evidence) == 251


@pytest.mark.parametrize("text", [
    "How many walls are shown on the floor plan of 'Missing'?",
    "How many walls are shown on the floor plan of 'Missing model'?",
    "How many walls are there?",
    "How many walls in the model 'Test model' on the floor 'Ground'?",
    "How many walls are on 'Ground' and 'Other'?",
])
def test_unknown_or_ambiguous_scope_abstains_without_llm(model, text):
    _, _, element, save, _ = model
    element()
    a = ask(save(), text)
    assert a.value is None and a.lane == "ifc"
    assert "scope=" in a.note


@pytest.mark.parametrize("text", [
    "How many walls are there in the model 'Model Ground floor'?",
    "Mitu seina on mudelis „Test model“?",
    "Hvor mange vægge er der i modellen 'Test model'?",
    "Wie viele Wände enthält das Modell „Test model“?",
    "How many walls are there in the whole model?",
])
def test_explicit_model_scope_is_independent_of_quoted_label(model, text):
    _, _, element, save, _ = model
    element()
    assert ask(save(), text).value == 1


def test_duplicate_storey_names_abstain(model):
    f, _, element, save, _ = model
    element()
    f.create_entity("IfcBuildingStorey", GlobalId=ifcopenshell.guid.new(), Name="Ground")
    assert ask(save(), "How many walls on 'Ground'?").value is None


def test_aggregate_parts_are_not_double_counted(model):
    f, _, element, save, _ = model
    parent = element(cls="IfcStair")
    child = element(cls="IfcStair")
    f.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(),
                    RelatingObject=parent, RelatedObjects=[child])
    a = ask(save(), "How many stairs on 'Ground'?")
    assert a.value == 1
    assert [e.global_id for e in a.evidence] == [parent.GlobalId]


@pytest.mark.parametrize("text,quantities,expected,unit", [
    ("total length", {"Length": 2500.0}, 2.5, "m"),
    ("total net side area", {"NetSideArea": 12.0}, 12.0, "m2"),
    ("total net volume", {"NetVolume": 3.0}, 3.0, "m3"),
    ("total net side area", {"NetSideArea": 0.0}, 0.0, "m2"),
])
def test_quantity_types_use_their_own_units(model, text, quantities, expected, unit):
    _, _, element, save, _ = model
    e = element(quantities=quantities)
    a = ask(save(), f"What is the {text} of all walls on 'Ground'?")
    assert a.value == expected and a.unit == unit
    assert [ev.global_id for ev in a.evidence] == [e.GlobalId]
    assert "Qto" in a.note


@pytest.mark.parametrize("qty,text", [("Length", "length"), ("NetSideArea", "side area"), ("NetVolume", "volume")])
def test_missing_quantities_never_produce_partial_totals(model, qty, text):
    _, _, element, save, _ = model
    ids = {element(quantities={qty: 2.0}).GlobalId, element().GlobalId}
    a = ask(save(), f"What is the total net {text} of all walls on 'Ground'?")
    assert a.value is None and "incomplete total: 1/2" in a.note
    assert {e.global_id for e in a.evidence} == ids


def test_space_total_abstains_if_one_room_has_no_area(model):
    _, _, element, save, _ = model
    element(cls="IfcSpace", quantities={"NetFloorArea": 10.0})
    element(cls="IfcSpace")
    a = ask(save(), "What is the total net floor area of all rooms on 'Ground'?")
    assert a.value is None and "incomplete total" in a.note


def test_zero_room_area_is_available_not_missing(model):
    _, _, element, save, _ = model
    element(cls="IfcSpace", name="Void", quantities={"NetFloorArea": 0.0})
    a = ask(save(), "What is the net floor area of room 'Void' on 'Ground'?")
    assert a.value == 0.0 and a.unit == "m2"


def test_quantity_unit_override_takes_precedence_over_project_units(model):
    f, _, element, save, _ = model
    element(quantities={"Length": 2.5})
    f.by_type("IfcQuantityLength")[0].Unit = ifcopenshell.api.unit.add_si_unit(f)
    a = ask(save(), "What is the total length of all walls on 'Ground'?")
    assert a.value == 2.5 and a.unit == "m"


def test_quoted_room_or_model_labels_do_not_change_entity_or_quantity(model):
    _, _, element, save, _ = model
    element()
    a = ask(save(), "How many walls in the model 'Door volume test'?")
    assert a.value == 1 and a.unit == "count"


def test_whole_model_net_floor_area_is_not_an_ambiguous_floor_reference(model):
    _, _, element, save, _ = model
    element(cls="IfcSpace", quantities={"NetFloorArea": 15.0})
    a = ask(save(), "What is the total net floor area of all rooms in the model 'Test'?")
    assert a.value == 15.0 and a.unit == "m2"


def test_gross_area_is_not_substituted_for_missing_net_area(model):
    _, _, element, save, _ = model
    element(quantities={"GrossSideArea": 20.0})
    a = ask(save(), "What is the total net side area of all walls on 'Ground'?")
    assert a.value is None and "incomplete total" in a.note


def test_duplicate_room_labels_abstain(model):
    _, _, element, save, _ = model
    for _ in range(2):
        element(cls="IfcSpace", name="Office", quantities={"NetFloorArea": 10.0})
    a = ask(save(), "What is the net floor area of room 'Office' on 'Ground'?")
    assert a.value is None and "not unique" in a.note


def test_companion_resolution_does_not_use_arbitrary_prefixes(model):
    _, _, element, save, folder = model
    element()
    save()
    (folder / "test-unrelated.svg").write_text('<svg><g class="IfcWall"/></svg>')
    a = ask("data/ifc_models/test-unrelated.svg", "How many walls in the model 'Test'?")
    assert a.value is None and "companion IFC" in a.note


def test_missing_ifc_never_counts_partial_svg_inventory(model):
    _, _, _, _, folder = model
    (folder / "absent_plan-01-ground.svg").write_text('<svg><g class="IfcWall"/></svg>')
    a = ask("data/ifc_models/absent_plan-01-ground.pdf", "How many walls in the model 'Absent'?")
    assert a.value is None and "complete inventory unavailable" in a.note


def test_exact_uppercase_ifc_twin_resolves(model):
    _, _, element, save, folder = model
    element()
    save()
    (folder / "test.ifc").rename(folder / "test.IFC")
    a = ask("data/ifc_models/test.pdf", "How many walls in the model 'Test'?")
    assert a.value == 1 and a.evidence[0].file.endswith("test.IFC")


def test_exact_twin_takes_precedence_over_plan_prefix(model):
    _, _, element, save, _ = model
    element()
    save()
    element()
    save("test_plan-01-ground")
    a = ask("data/ifc_models/test_plan-01-ground.pdf", "How many walls in the model 'Test'?")
    assert a.value == 2 and a.evidence[0].file.endswith("test_plan-01-ground.ifc")


def test_selected_full_dataset_pdf_has_complete_model_evidence(monkeypatch):
    root = data.ROOT.resolve().parent / "junction-dataset"
    path = "data/ifc_models/bsc-esplanades_1807-ep-ar-v18_plan-01-1-korrus.pdf"
    if not (root / path).exists():
        pytest.skip("full dataset not available")
    monkeypatch.setattr(data, "ROOT", root)
    monkeypatch.setattr(cli, "ROOT", root)
    a = cli.ask(path, "How many doors are there in the model 'Maleva tänav 18 korterelamu (Esplanades example model)'?")
    assert a["value"] == 211
    assert len({e["global_id"] for e in a["evidence"]}) == 211


@pytest.mark.parametrize("quantity,expected,unit", [
    ("length", 185.129, "m"), ("net volume", 177.896, "m3"),
])
def test_selected_full_dataset_pdf_uses_companion_quantity_units(monkeypatch, quantity, expected, unit):
    root = data.ROOT.resolve().parent / "junction-dataset"
    path = "data/ifc_models/bsc-molio_molio-with-uris_plan-03-grundplan.pdf"
    if not (root / path).exists():
        pytest.skip("full dataset not available")
    monkeypatch.setattr(data, "ROOT", root)
    a = ask(path, f"What is the total {quantity} of all walls on 'Grundplan'?")
    assert a.value == pytest.approx(expected, rel=0.02) and a.unit == unit


def test_all_missing_fzk_model_questions_abstain():
    if not (data.ROOT / "questions.jsonl").exists():
        pytest.skip("dataset not available")
    if any((data.ROOT / "data" / "ifc_models").glob("*fzk*.ifc")):
        pytest.skip("missing-model fixture is now present; independent missing-companion cases remain covered")
    qs = [q for q in data.load_questions() if q.source == "ifc_models" and "fzk" in q.path]
    assert qs
    for q in qs:
        a = answer(q)
        assert a.value is None and "companion IFC" in a.note
