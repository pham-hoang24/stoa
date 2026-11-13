import pytest

from stoa.data import ROOT

needs_data = pytest.mark.skipif(not (ROOT / "questions.jsonl").exists(), reason="dataset not available (set STOA_DATASET)")
