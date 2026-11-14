"""Seam: stoa.eval.run.main — correctness and evidence are reported separately, per lane. Router and dataset are faked."""
from stoa.answer import Answer, Evidence
from stoa.data import Question
from stoa.eval import run


def test_report_separates_correctness_from_evidence(monkeypatch, capsys):
    qs = [Question(path=f"data/swiss_dwellings/{i}.pdf", question="x", answer=1, type="count") for i in range(4)]
    answers = iter([
        Answer(1, "count", [Evidence("f")], "swiss"),  # correct, with evidence
        Answer(1, "count", [], "swiss"),               # correct, no evidence
        Answer(2, "count", [Evidence("f")], "swiss"),  # wrong, with evidence
        Answer(None, lane="swiss"),                    # abstain
    ])
    monkeypatch.setattr(run, "load_questions", lambda: qs)
    monkeypatch.setattr(run, "answer", lambda q: next(answers))

    assert run.main([]) == 0
    row = next(l for l in capsys.readouterr().out.splitlines() if l.startswith("lane"))
    assert "n=    4" in row
    assert "acc= 50.0%" in row        # 2 of 4 correct
    assert "abstain= 25.0%" in row    # 1 of 4
    assert "evidence= 66.7%" in row   # 2 of the 3 answered carry evidence
