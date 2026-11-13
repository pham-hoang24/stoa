"""Seam: stoa.router.lane_for — lane chosen by source/format, not by question type."""
from stoa.data import Question
from stoa.router import lane_for


def lane(path):
    return lane_for(Question(path=path, question="x"))


def test_routes_by_source_and_format():
    assert lane("data/swiss_dwellings/a.pdf") == "swiss"
    assert lane("data/ifc_models/a.ifc") == "ifc"
    assert lane("data/ifc_models/a_plan.pdf") == "ifc"
    assert lane("data/ifc_bench/a.ifc") == "ifc"
    assert lane("data/cubicasa5k/a.png") == "vision"
    assert lane("data/opening_design/Sports_Complex/Sheet A-801.pdf") == "doc"
