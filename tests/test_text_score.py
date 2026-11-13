import pytest

from stoa.text_score import correct_text, main


@pytest.mark.parametrize("truth,pred", [
    ("IFC Schema: IFC4", "ifc schema — IFC4."),
    (" Café\n office ", "CAFÉ office"),
    ("Information is not available in the BIM model.", None),
    ("No door types have fire rating information in this model.", "Fire rating data not specified."),
    ("This information is not available in the BIM model.", "The capacity is not explicitly provided in the given data."),
])
def test_normalized_and_explicit_abstention_matches(truth, pred):
    assert correct_text(truth, pred)


@pytest.mark.parametrize("truth,pred", [
    ("There are 20 walls", "There are 20 doors"),
    ("IFC4", "IFC2X3"),
    ("Elevation -3.0 m", "Elevation 3.0 m"),
    ("Load bearing: 50%", "Load bearing: 50"),
    ("Total Rooms: 21", None),
    ("Information is not available.", "Capacity is 200 kPa"),
    ("Unavailable, however estimated at 66 m2", None),
    ("Not available. Based on geometry it is a wood structure.", None),
    ("Information is not available.", "Not available, but probably safe."),
    ("Information is not available.", "Information is not available. The building is safe."),
    ("Building Name: Tower; Usage: not defined", None),
    ("", ""),
])
def test_overlap_and_mixed_references_do_not_establish_correctness(truth, pred):
    assert not correct_text(truth, pred)


def test_dump_scorer_does_not_count_unattempted_questions(tmp_path, capsys):
    p = tmp_path / "results.jsonl"
    p.write_text('{"truth":"IFC4","pred":"IFC4"}\n'
                 '{"truth":"not available","pred":null,"attempted":false}\n')
    assert main([str(p)]) == 0
    assert "1/1" in capsys.readouterr().out
