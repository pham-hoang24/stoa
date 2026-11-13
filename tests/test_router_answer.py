"""Seam: stoa.router.answer — dispatch, IFC->LLM fallback, crash containment. Lanes are faked at router._lane_module."""
import types

import pytest

from stoa import router
from stoa.answer import ABSTAIN_DECLINED, ABSTAIN_DEFER, Answer
from stoa.data import Question


def fake_lane(name, value=None, note="", boom=False, abstain=None):
    calls = []

    def answer(q, path):
        calls.append(q)
        if boom:
            raise ValueError("kaput")
        return Answer(value, lane=name, note=note, abstain=abstain)

    return types.SimpleNamespace(answer=answer, calls=calls)


@pytest.fixture
def lanes(monkeypatch):
    table = {n: fake_lane(n, value=1) for n in router.LANE_MODULES}
    monkeypatch.setattr(router, "_lane_module", lambda lane: table[lane])
    return table


def q(path, qtype="count"):
    return Question(path=path, question="x", type=qtype)


def test_dispatches_to_lane_for_source(lanes):
    assert router.answer(q("data/swiss_dwellings/a.pdf")).lane == "swiss"
    assert router.answer(q("data/cubicasa5k/a.png")).lane == "vision"


def test_ifc_answer_is_kept_when_it_has_a_value(lanes):
    assert router.answer(q("data/ifc_models/a.ifc")).lane == "ifc"
    assert lanes["doc"].calls == []


def test_deferred_abstain_falls_back_to_llm(lanes):
    lanes["ifc"] = fake_lane("ifc", abstain=ABSTAIN_DEFER)
    assert router.answer(q("data/ifc_models/a.ifc")).lane == "doc"


@pytest.mark.parametrize("path,qtype,note", [
    ("data/ifc_models/a.ifc", "text", "unsupported entity"),
    ("data/ifc_bench/a.ifc", "count", "ambiguous scope"),
    ("data/ifc_models/a.ifc", "count", "entity not recognised"),
])
def test_declined_abstain_never_reaches_llm(lanes, path, qtype, note):
    """Unresolved scope must stay abstained, whatever the question type, path or note text."""
    lanes["ifc"] = fake_lane("ifc", note=note, abstain=ABSTAIN_DECLINED)
    a = router.answer(q(path, qtype))
    assert a.value is None and a.lane == "ifc" and lanes["doc"].calls == []


def test_lane_crash_becomes_abstain(lanes):
    lanes["swiss"] = fake_lane("swiss", boom=True)
    a = router.answer(q("data/swiss_dwellings/a.pdf"))
    assert a.value is None and a.lane == "swiss" and a.note == "error: ValueError: kaput"
