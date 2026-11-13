"""Independent IFC fixtures and router checks for deterministic text answers."""
import ifcopenshell
import ifcopenshell.api.unit
import pytest

from stoa import cli, data
from stoa.answer import Answer
from stoa.lanes import ifc_text, llm


@pytest.fixture
def model(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    folder = tmp_path / "data" / "ifc_bench"
    folder.mkdir(parents=True)
    f = ifcopenshell.file(schema="IFC4")
    project = f.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Test Project")
    building = f.create_entity("IfcBuilding", GlobalId=ifcopenshell.guid.new(), Name="Tower", ObjectType="OFFICE")
    developer = f.create_entity("IfcOrganization", Name="Test Developer")
    f.create_entity("IfcApplication", ApplicationDeveloper=developer, Version="42.0",
                    ApplicationFullName="TestCAD", ApplicationIdentifier="Test")
    f.header.file_name.originating_system = "Test exporter 7.1"
    units = [ifcopenshell.api.unit.add_si_unit(f, unit_type=k, prefix=p)
             for k, p in [("LENGTHUNIT", "MILLI"), ("AREAUNIT", None)]]
    ifcopenshell.api.unit.assign_unit(f, units=units)
    levels = [f.create_entity("IfcBuildingStorey", GlobalId=ifcopenshell.guid.new(), Name=name, Elevation=e)
              for name, e in [("Ground", 0.0), ("Level 1", 3000.0)]]
    for i, level in enumerate(levels):
        space = f.create_entity("IfcSpace", GlobalId=ifcopenshell.guid.new(), Name=f"R{i}", LongName="Office")
        f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                        RelatedElements=[space], RelatingStructure=level)
        qty = f.create_entity("IfcQuantityArea", Name="NetFloorArea", AreaValue=10.0 * (i + 1))
        qto = f.create_entity("IfcElementQuantity", GlobalId=ifcopenshell.guid.new(),
                              Name="BaseQuantities", Quantities=[qty])
        f.create_entity("IfcRelDefinesByProperties", GlobalId=ifcopenshell.guid.new(),
                        RelatedObjects=[space], RelatingPropertyDefinition=qto)

    def save():
        p = folder / "custom.ifc"
        f.write(str(p))
        return p

    def ask(text):
        a = ifc_text.answer(text, save())
        assert a is not None
        return a

    return f, building, levels, save, ask


def test_software_reads_schema_header_and_all_application_metadata(model):
    _, _, _, _, ask = model
    a = ask("Which software and modeling standards were used?")
    assert "IFC4" in a.value and "TestCAD" in a.value and "42.0" in a.value
    assert "Test exporter 7.1" in a.value and "Test Developer" in a.value
    assert a.evidence and "IfcApplication #" in a.evidence[0].label
    assert a.evidence[0].global_id is None  # IFC applications have STEP IDs, not GlobalIds


def test_building_usage_is_read_only_when_explicit(model):
    _, building, _, _, ask = model
    a = ask("What is the building's type and its function?")
    assert "Tower" in a.value and "OFFICE" in a.value
    building.ObjectType = None
    a = ask("What is the building's type and its function?")
    assert a.value is None and "no usage inferred" in a.note


def test_duplicate_buildings_decline_ambiguous_scope(model):
    f, _, _, _, ask = model
    f.create_entity("IfcBuilding", GlobalId=ifcopenshell.guid.new(), Name="Other")
    assert ask("What is the building name?").value is None


def test_all_storeys_include_empty_records_and_use_length_units(model):
    f, _, _, _, ask = model
    f.create_entity("IfcBuildingStorey", GlobalId=ifcopenshell.guid.new(), Name="Roof", Elevation=6000.0)
    a = ask("What are the names and number of levels?")
    assert "Number of Levels: 3" in a.value
    assert "Level 1: elevation 3 m" in a.value and "Roof: elevation 6 m" in a.value
    assert len(a.evidence) == 3


def test_named_space_inventory_has_complete_ids_and_explicit_net_areas(model):
    f, _, _, _, ask = model
    a = ask("What spaces are on Level 1, with their room names and areas?")
    assert "Total Spaces: 1" in a.value and "R1: Office; 20.00 m2" in a.value
    assert f.by_type("IfcSpace")[1].GlobalId in {e.global_id for e in a.evidence}


def test_all_level_inventory_includes_both_rooms(model):
    _, _, _, _, ask = model
    a = ask("What is the complete space breakdown for all building levels, listing room names and areas?")
    assert "Total Spaces: 2" in a.value
    assert "10.00 m2" in a.value and "20.00 m2" in a.value


@pytest.mark.parametrize("scope", ["Missing", "first floor", "ground floor"])
def test_space_scope_never_guesses_an_ordinal_floor(model, scope):
    _, _, _, _, ask = model
    a = ask(f"What spaces are on '{scope}', with their areas?")
    assert a.value is None and "scope unresolved" in a.note


def test_space_area_does_not_silently_skip_missing_quantities(model):
    f, _, _, _, ask = model
    f.by_type("IfcQuantityArea")[0].Name = "GrossFloorArea"
    a = ask("What is the space breakdown by level with room areas?")
    assert a.value is None and "incomplete areas" in a.note


def test_zero_area_is_not_unavailable(model):
    f, _, _, _, ask = model
    f.by_type("IfcQuantityArea")[0].AreaValue = 0.0
    assert "0.00 m2" in ask("What spaces are on 'Ground', with areas?").value


def test_absent_fire_rating_declines_with_element_citations(model):
    f, _, _, _, ask = model
    door = f.create_entity("IfcDoor", GlobalId=ifcopenshell.guid.new(), Name="Door")
    a = ask("Which door types have fire rating information?")
    assert a.value is None and "not available" in a.note
    assert a.evidence[0].global_id == door.GlobalId


def test_mep_counts_do_not_infer_system_type_from_names(model):
    f, _, _, _, ask = model
    terminal = f.create_entity("IfcAirTerminal", GlobalId=ifcopenshell.guid.new(), Name="Heating-looking name")
    a = ask("What MEP systems are present in this building?")
    assert "Total MEP Components: 1" in a.value and "Explicit IfcSystem records: 0" in a.value
    a = ask("How many MEP components are there by system type?")
    assert a.value is None and "system classification unavailable" in a.note
    assert a.evidence[0].global_id == terminal.GlobalId


def test_explicit_system_membership_is_counted(model):
    f, _, _, _, ask = model
    terminal = f.create_entity("IfcAirTerminal", GlobalId=ifcopenshell.guid.new(), Name="Terminal")
    system = f.create_entity("IfcSystem", GlobalId=ifcopenshell.guid.new(), Name="Supply", ObjectType="VENTILATION")
    f.create_entity("IfcRelAssignsToGroup", GlobalId=ifcopenshell.guid.new(),
                    RelatedObjects=[terminal], RelatingGroup=system)
    a = ask("How many MEP components are there by system type?")
    assert "System Supply: 1 components" in a.value
    assert "System Type VENTILATION: 1 components" in a.value


def test_system_names_do_not_establish_system_types(model):
    f, _, _, _, ask = model
    terminal = f.create_entity("IfcAirTerminal", GlobalId=ifcopenshell.guid.new())
    system = f.create_entity("IfcSystem", GlobalId=ifcopenshell.guid.new(), Name="Heating")
    f.create_entity("IfcRelAssignsToGroup", GlobalId=ifcopenshell.guid.new(),
                    RelatedObjects=[terminal], RelatingGroup=system)
    a = ask("How many MEP components are there by system type?")
    assert a.value is None and "names are not treated as system types" in a.note


def test_all_level_inventory_does_not_drop_unassigned_spaces(model):
    f, _, _, _, ask = model
    f.create_entity("IfcSpace", GlobalId=ifcopenshell.guid.new(), Name="Orphan")
    a = ask("List the names of all rooms across all levels")
    assert a.value is None and "incomplete inventory" in a.note


def test_unsupported_semantic_or_multi_operation_questions_defer(model):
    _, _, _, save, _ = model
    for text in ["Estimate embodied carbon", "What is the floor area, footprint and number of levels?",
                 "What is the space distribution by level with primary functions and percentages?",
                 "What software was used and what is the live load capacity?",
                 "What is the building name and its total floor area?"]:
        assert ifc_text.answer(text, save()) is None


def test_cached_model_reloads_after_file_changes(model):
    _, building, _, _, ask = model
    assert "Tower" in ask("What is the building name?").value
    building.Name = "Changed building"
    assert "Changed building" in ask("What is the building name?").value


def test_repeated_metadata_requests_reuse_the_parsed_model(model, monkeypatch):
    _, _, _, save, _ = model
    path = save()
    real_open, calls = ifcopenshell.open, []

    def counted_open(filename):
        calls.append(filename)
        return real_open(filename)

    monkeypatch.setattr(ifcopenshell, "open", counted_open)
    ifc_text._open.cache_clear()
    for _ in range(5):
        assert "TestCAD" in ifc_text.answer("Which software was used?", path).value
    assert len(calls) == 1


def test_router_does_not_fallback_for_missing_attributes(model, monkeypatch):
    _, building, _, save, _ = model
    building.ObjectType = None
    save()
    monkeypatch.setattr(llm, "answer", lambda *args: pytest.fail("missing attributes must not reach an LLM"))
    a = cli.ask("data/ifc_bench/custom.ifc", "What is the building's type and its function?")
    assert a["value"] is None and a["abstain"] == "declined"


def test_router_defers_only_unsupported_text(model, monkeypatch):
    _, _, _, save, _ = model
    save()
    monkeypatch.setattr(llm, "answer", lambda *args: Answer("fallback", lane="llm"))
    a = cli.ask("data/ifc_bench/custom.ifc", "Estimate embodied carbon")
    assert a["value"] == "fallback" and a["lane"] == "llm"


@pytest.mark.parametrize("filename,software,schema", [
    ("ac20_arc.ifc", "ARCHICAD-64", "IFC4"),
    ("digital_hub_arc.ifc", "Autodesk Revit 2019", "IFC4"),
    ("fantasy_office_building_3_arc.ifc", "Autodesk Revit 2024", "IFC4"),
    ("hitos_arc.ifc", "ArchiCAD 11.0", "IFC2X3"),
])
def test_real_software_metadata_is_answered_without_a_provider(filename, software, schema, monkeypatch):
    path = f"data/ifc_bench/{filename}"
    if not (data.ROOT / path).exists():
        pytest.skip("preview model unavailable")
    monkeypatch.setattr(cli, "ROOT", data.ROOT)
    monkeypatch.setattr(llm, "answer", lambda *args: pytest.fail("metadata must be deterministic"))
    a = cli.ask(path, "What software and modeling standards were used?")
    assert a["lane"] == "ifc" and software in a["value"] and schema in a["value"]
    assert a["evidence"] and all(e["file"].endswith(filename) for e in a["evidence"])


def test_real_placeholder_capacity_is_a_terminal_abstention(monkeypatch):
    path = "data/ifc_bench/duplex_arc.ifc"
    if not (data.ROOT / path).exists():
        pytest.skip("preview model unavailable")
    monkeypatch.setattr(cli, "ROOT", data.ROOT)
    monkeypatch.setattr(llm, "answer", lambda *args: pytest.fail("absent capacity must stay declined"))
    a = cli.ask(path, "What is the live load capacity of the first floor?")
    assert a["value"] is None and a["abstain"] == "declined" and a["lane"] == "ifc"
