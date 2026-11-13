"""Seam: the Swiss lane through router.answer. Expected values are dataset ground truth (questions.jsonl), not recomputed."""
import pytest

from conftest import ask as ask_about, needs_data

FLOOR = "data/swiss_dwellings/site1000_bldg2082_floor9385.pdf"
pytestmark = needs_data


def ask(text):
    return ask_about(FLOOR, text)


@pytest.mark.parametrize("text,expected", [
    ("How many apartments (residential units) are shown on this floor plan?", 4),
    ("How many doors (interior doors and entrance doors together) are drawn on this floor plan?", 36),
    ("How many windows are drawn on this floor plan?", 28),
    ("How many toilets (WC) are drawn on this floor plan?", 4),
    ("How many washbasins are drawn on this floor plan?", 4),
    ("How many bathtubs are drawn on this floor plan?", 4),
    ("Wie viele Räume mit der Bezeichnung «Zimmer» gibt es in diesem Geschoss?", 12),
])
def test_counts_are_exact(text, expected):
    assert ask(text).value == expected


def test_room_area_from_polygon():
    assert ask("What is the net floor area of room 2.10 ('Zimmer') in m²?").value == pytest.approx(16.78, rel=0.02)


def test_total_area_of_rooms_with_label():
    assert ask("What is the total net area in m² of all rooms labelled 'Zimmer' on this floor?").value == pytest.approx(184.93, rel=0.02)


def test_apartment_area_excludes_outdoor_spaces():
    q = "What is the net floor area of apartment A in m², summing all its rooms except balconies, loggias, terraces and other outdoor spaces?"
    assert ask(q).value == pytest.approx(80.34, rel=0.02)


def test_translation_gives_same_answer():
    assert ask("Wie viele Fenster sind auf diesem Grundriss eingezeichnet?").value == 28


def test_evidence_box_lands_on_the_pdf_page():
    ev = ask("What is the net floor area of room 2.01 ('Zimmer') in m²?").evidence[0]
    assert ev.file.endswith(".pdf") and ev.page == 0
    x0, y0, x1, y1 = ev.bbox
    assert 0 <= x0 < x1 <= 1191 and 0 <= y0 < y1 <= 842  # A3 landscape in points
    assert x0 < 535 < x1 and y0 < 100 < y1  # contains the printed 'Zimmer 2.01' label near (524..546, 90..104)


def test_room_boundary_polygon_is_returned_in_pdf_points():
    ev = ask("What is the net floor area of room 2.01 ('Zimmer') in m²?").evidence[0]
    assert ev.polygon and len(ev.polygon) >= 3
    xs, ys = [p[0] for p in ev.polygon], [p[1] for p in ev.polygon]
    assert (min(xs), min(ys), max(xs), max(ys)) == pytest.approx(ev.bbox, abs=1e-6)


def test_missing_room_abstains_with_reason():
    a = ask("What is the net floor area of room 9.99 ('Zimmer') in m²?")
    assert a.value is None and a.abstain == "declined" and "9.99" in a.note


def test_missing_apartment_abstains_with_reason():
    a = ask("What is the net floor area of apartment Z in m², summing all its rooms except balconies, loggias, terraces and other outdoor spaces?")
    assert a.value is None and a.abstain == "declined" and "Z" in a.note


def test_pdf_without_dxf_twin_abstains(tmp_path, monkeypatch):
    from stoa import data
    from stoa.data import Question
    from stoa.router import answer
    (tmp_path / "data" / "swiss_dwellings").mkdir(parents=True)
    (tmp_path / "data" / "swiss_dwellings" / "lonely.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(data, "ROOT", tmp_path)
    a = answer(Question(path="data/swiss_dwellings/lonely.pdf", question="How many doors are drawn on this floor plan?"))
    assert a.value is None and a.abstain == "declined" and "DXF twin" in a.note


def test_unrecognised_question_defers_instead_of_guessing():
    from stoa.lanes import swiss
    from stoa.data import Question, ROOT
    a = swiss.answer(Question(path=FLOOR, question="Who designed this building?"), ROOT / FLOOR)
    assert a.value is None and a.abstain == "defer"
