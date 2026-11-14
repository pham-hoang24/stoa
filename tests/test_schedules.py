"""Schedule behavior on independent vector/raster PDF fixtures and real sheets."""
from pathlib import Path

import pymupdf
import pytest

from stoa import cli, data, router, viewer
from stoa.data import Question
from stoa.lanes import llm
from stoa.lanes.schedules import answer


def table(page, title, headers, records, y=30):
    widths = [55 if h != "Type" else 165 for h in headers]
    xs = [20]
    for width in widths:
        xs.append(xs[-1] + width)
    height = 30
    bottom = y + height * (len(records) + 2)
    page.draw_rect(pymupdf.Rect(xs[0], y, xs[-1], bottom))
    for i in range(1, len(records) + 2):
        yy = y + height * i
        page.draw_line((xs[0], yy), (xs[-1], yy))
    for x in xs[1:-1]:
        page.draw_line((x, y + height), (x, bottom))
    page.insert_text((xs[0] + 2, y + 10), title, fontsize=7)
    for i, cells in enumerate([headers, *records]):
        for x, value in zip(xs, cells):
            page.insert_text((x + 2, y + height * (i + 1) + 10), value, fontsize=6)


@pytest.fixture
def pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(viewer, "ROOT", tmp_path)
    monkeypatch.setattr(llm, "answer", lambda *args: pytest.fail("schedules must never reach a model"))
    monkeypatch.setattr(pymupdf.Page, "get_layout", lambda *args, **kwargs: pytest.fail("native parser must disable layout-model inference"), raising=False)
    folder = tmp_path / "data" / "opening_design"
    folder.mkdir(parents=True)
    path = folder / "Schedule.pdf"

    def save(title="DOOR SCHEDULE - TYPE", headers=None, records=None, rotated=False, raster=False):
        headers = headers or ["Count", "Type Mark", "Type", "Width", "Height"]
        if records is None:
            records = [["3", "U10", "SWING - FLUSH", "3'-0\"", "7'-0\""],
                       ["4", "U11", "SLIDING - FLUSH", "5'-0\"", "8'-0\""]]
        with pymupdf.open() as doc:
            page = doc.new_page(width=900, height=600)
            table(page, title, headers, records)
            if rotated:
                with pymupdf.open() as out:
                    p = out.new_page(width=600, height=900)
                    p.show_pdf_page(p.rect, doc, 0, rotate=90)
                    p.set_rotation(90)
                    out.save(path)
            elif raster:
                image = page.get_pixmap().tobytes("png")
                with pymupdf.open() as out:
                    p = out.new_page(width=900, height=600)
                    p.insert_image(p.rect, stream=image)
                    p.insert_text((650, 580), "Vector title block only")
                    out.save(path)
            else:
                doc.save(path)
        return path

    def ask(text, **kwargs):
        return answer(Question("data/opening_design/Schedule.pdf", text, **kwargs), path)

    return save, ask


def test_weighted_type_counts_use_quantity_not_row_count(pdf):
    save, ask = pdf
    save()
    a = ask("How many items in total are in the door type schedule (all type marks)?")
    assert a.value == 7 and a.unit == "count" and len(a.evidence) == 2
    assert all(e.page == 0 and e.bbox and e.file == "data/opening_design/Schedule.pdf" for e in a.evidence)


def test_specific_and_zero_type_counts_are_distinct_from_missing_attribute(pdf):
    save, ask = pdf
    save()
    assert ask("How many doors of type U10 are scheduled?").value == 3
    assert ask("How many doors of type U99 are scheduled?").value == 0
    assert ask("What is the width of door type U99?").value is None


def test_feet_inches_are_preserved(pdf):
    save, ask = pdf
    save(records=[["2", "U10", "SWING", "5'-10 3/8\"", "7'-0\""]])
    a = ask("What are the width and height of door type U10?")
    assert a.value == "5'-10 3/8\" wide x 7'-0\" high"


def test_dimension_and_description_filters_are_applied(pdf):
    save, ask = pdf
    save()
    assert ask("How many doors whose description starts with 'SWING' are scheduled?").value == 3
    assert ask("How many doors are 3'-0\" wide?").value == 3


@pytest.mark.parametrize("bad", ["", "three", "-2"])
def test_incomplete_weighted_inventory_does_not_produce_partial_totals(pdf, bad):
    save, ask = pdf
    save(records=[[bad, "U10", "SWING", "3'-0\"", "7'-0\""],
                  ["4", "U11", "SLIDING", "5'-0\"", "8'-0\""]])
    a = ask("How many items in total are counted in the door type schedule?")
    assert a.value is None and a.abstain == "declined"


def test_duplicate_marks_abstain(pdf):
    save, ask = pdf
    save(records=[["2", "U10", "SWING", "3'-0\"", "7'-0\""],
                  ["4", "U10", "SLIDING", "5'-0\"", "8'-0\""]])
    a = ask("How many doors of type U10 are scheduled?")
    assert a.value is None and "duplicate" in a.note


def test_unsupported_filter_does_not_turn_into_total(pdf):
    save, ask = pdf
    save()
    assert ask("How many doors are fire-rated?").value is None


def test_scanned_schedule_with_vector_title_does_not_trigger_ocr_or_guess(pdf):
    save, ask = pdf
    save(raster=True)
    a = ask("How many items in total are listed in the door type schedule?")
    assert a.value is None and a.abstain == "declined"


def test_rotated_source_evidence_matches_viewer_coordinates(pdf):
    save, ask = pdf
    path = save(rotated=True)
    a = ask("How many doors of type U10 are scheduled?")
    assert a.value == 3
    e = a.evidence[0]
    with pymupdf.open(path) as doc:
        page = doc[0]
        assert page.rotation == 90  # parser did not modify the source
        word = next(w for w in page.get_text("words") if w[4] == "U10")
        region = pymupdf.Rect(word[:4]) * page.rotation_matrix
        assert region in pymupdf.Rect(e.bbox)
    assert viewer._safe(e.file) == path.resolve()
    png, zoom = viewer.render(path)
    assert pymupdf.Pixmap(png).width == 1800 and zoom == 2


def test_window_assembly_expansion_is_explicit(pdf):
    save, ask = pdf
    save("WINDOW SCHEDULE - SIMPLIFIED", ["Type Mark", "Type", "Count", "Width", "Height"],
         [["AA", "1-WIDE", "2", "35 1/2\"", "77 1/2\""],
          ["BB", "2-WIDE", "3", "35 1/2\"", "77 1/2\""]])
    assert ask("How many windows are listed in total?").value == 5
    assert ask("If every N-wide assembly consists of N units, how many window units are needed in total?").value == 8


def test_reference_answer_is_not_an_input_to_parsing(pdf):
    save, ask = pdf
    save()
    assert ask("How many doors of type U10 are scheduled?", answer=999).value == 3


def test_merged_room_rows_and_square_foot_areas_are_preserved(pdf):
    save, ask = pdf
    headers = ["Area", "Room Number", "Room Name", "Floor Finish", "Base Finish",
               "North Wall", "South Wall", "East Wall", "West Wall", "Ceiling Finish"]
    save("FINISH ROOM SCHEDULE", headers,
         [["100 SF\n200 SF", "101\n102", "OFFICE\nOFFICE", "F0\nF4", "", "", "", "", "", ""]])
    a = ask("What is the total area of rooms named OFFICE?")
    assert a.value == 300 and a.unit == "ft2" and len(a.evidence) == 2
    assert ask("How many rooms are listed in the finish room schedule?").value == 2
    assert ask("What is the area of room 102?").value == 200
    assert ask("What is the area of room 102 in m2?", unit="m2").value is None


def test_incomplete_room_areas_require_explicit_listed_area_scope(pdf):
    save, ask = pdf
    save("FINISH ROOM SCHEDULE", ["Area", "Room Number", "Room Name", "Floor Finish"],
         [["100 SF", "101", "OFFICE", "F0"], ["Redundant Room", "102", "TENANT", ""]])
    assert ask("What is the total area of all rooms?").value is None
    assert ask("What is the total area of all rooms that have an area listed?").value == 100


def test_wrong_sheet_abstains(pdf):
    save, ask = pdf
    save()
    a = ask("On sheet A999, how many doors of type U10 are scheduled?")
    assert a.value is None and "selected drawing" in a.note


def test_public_router_is_deterministic_and_keeps_declines(pdf):
    save, _ = pdf
    save()
    assert cli.ask("data/opening_design/Schedule.pdf", "How many doors of type U10 are scheduled?")["value"] == 3
    assert cli.ask("data/opening_design/Schedule.pdf", "How many water closets are drawn?")["value"] is None


@pytest.mark.parametrize("index,expected,unit", [
    (0, 38, "count"), (1, 14, "count"), (9, 17, "count"), (23, 29, "count"),
    (24, 29690, "ft2"), (26, 3814, "ft2"), (28, 49560, "ft2"),
    (44, 71, "count"), (50, 657, "count"), (56, 235, "count"), (62, 379, "count"),
])
def test_real_schedule_cases(index, expected, unit):
    if not (data.ROOT / "questions.jsonl").exists():
        pytest.skip("preview unavailable")
    qs = [q for q in data.load_questions() if q.source == "opening_design"]
    if len(qs) != 64:
        pytest.skip("preview cohort differs")
    q = qs[index]
    a = answer(q, q.abspath)
    assert a.value == expected and a.unit == unit
    assert a.evidence and all(e.page == 0 and e.bbox for e in a.evidence)
