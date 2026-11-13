import pytest

from stoa.data import ROOT, Question
from stoa.router import answer

needs_data = pytest.mark.skipif(not (ROOT / "questions.jsonl").exists(), reason="dataset not available (set STOA_DATASET)")


def ask(path, text):
    """Question through the public seam, router.answer."""
    return answer(Question(path=path, question=text))
