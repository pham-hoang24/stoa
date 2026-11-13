"""Seam: the IFC lane through router.answer, against ground truth literals."""
import pytest

from stoa.data import Question
from stoa.router import answer
from conftest import needs_data

pytestmark = needs_data
ESP = "data/ifc_models/bsc-esplanades_1807-ep-ar-v18.ifc"
MOL = "data/ifc_models/bsc-molio_molio-with-uris.ifc"


def ask(path, text):
    return answer(Question(path=path, question=text))


def test_space_area_falls_back_to_geometry_when_no_qto():
    a = ask(ESP, "What is the total net floor area of all rooms (spaces) on '1.korrus', in m²?")
    assert a.value == pytest.approx(870.29, rel=0.02)


def test_count_by_storey():
    assert ask(ESP, "How many doors are shown on the floor plan of '1.korrus'?").value == 46


def test_wall_length_uses_project_unit_scale():
    assert ask(MOL, "What is the total length of all walls on 'Grundplan', in metres?").value == pytest.approx(185.129, rel=0.02)


def test_estonian_question_resolves_same_entity():
    assert ask(ESP, "Mitu ust on näidatud korruse „1.korrus“ plaanil?").value == 46


def test_room_area_by_label_and_storey():
    a = ask(ESP, "What is the net floor area of the room 'ESIK (77-2)' on '5.korrus', in m²?")
    assert a.value == pytest.approx(5.1, rel=0.02)
    assert a.evidence[0].global_id  # citation points at an IFC element


def test_unknown_storey_abstains():
    assert ask(ESP, "How many doors are shown on the floor plan of 'No such floor'?").value is None


def test_floor_plan_pdf_resolves_to_its_ifc():
    a = ask("data/ifc_models/bsc-esplanades_1807-ep-ar-v18_plan-04-4-korrus.pdf", "How many doors are shown on the floor plan of '1.korrus'?")
    assert a.value == 46
