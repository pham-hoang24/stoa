"""Seam: the vision lane through router.answer with a stubbed provider (no network, no dataset needed).

These tests prove plumbing (validation, dedupe, counting, evidence, abstention). They say nothing about
detector accuracy: that is measured only by the live smoke eval (python -m stoa.eval.smoke_vision).
"""
import json

import cv2
import numpy as np
import pytest

from stoa import data
from stoa.data import Question
from stoa.lanes import llm
from stoa.router import answer

DOORS = "How many doors are shown on this floor plan?"
WINDOWS = "How many windows are shown on this floor plan?"


@pytest.fixture
def plan(tmp_path, monkeypatch):
    (tmp_path / "data" / "cubicasa5k").mkdir(parents=True)
    cv2.imwrite(str(tmp_path / "data" / "cubicasa5k" / "p.png"), np.full((200, 400, 3), 255, np.uint8))
    monkeypatch.setattr(data, "ROOT", tmp_path)
    return "data/cubicasa5k/p.png"


@pytest.fixture
def provider(monkeypatch):
    calls = []

    def stub(reply):
        monkeypatch.setattr(llm, "chat", lambda messages, **kw: calls.append(messages) or reply)
        return calls
    return stub


def dets(*boxes):
    """Detector reply for boxes given in source pixels of the 400x200 test image (provider speaks 0..1000 relative)."""
    return json.dumps({"detections": [{"box": [b[0] * 2.5, b[1] * 5, b[2] * 2.5, b[3] * 5]} for b in boxes]})


def ask(path, text):
    return answer(Question(path=path, question=text))


def test_counts_validated_boxes_with_numbered_evidence(plan, provider):
    provider(dets((10, 10, 40, 40), (100, 50, 130, 80), (300, 100, 330, 130)))
    a = ask(plan, DOORS)
    assert a.value == 3 and a.unit == "count" and a.lane == "vision" and a.abstain is None
    assert [e.label for e in a.evidence] == ["door 1", "door 2", "door 3"]
    assert a.evidence[0].bbox == pytest.approx((10, 10, 40, 40)) and a.evidence[0].file.endswith("p.png")


def test_duplicates_are_counted_once(plan, provider):
    provider(dets((10, 10, 40, 40), (11, 11, 41, 41), (100, 50, 130, 80)))
    assert ask(plan, WINDOWS).value == 2


def test_invalid_boxes_are_dropped_not_counted(plan, provider):
    provider(json.dumps({"detections": [
        {"box": [25, 50, 100, 200]},      # good: (10,10,40,40) px
        {"box": [125, 250, 127, 255]},    # tiny
        {"box": [0, 0, 1000, 1000]},      # whole image
        {"box": [5, 5, "x", 9]},          # not numbers
        {"box": [1, 2, 3]},               # wrong length
        {"nobox": 1},                     # no box
        {"box": [950, 900, 2000, 2000]},  # runs off the image: clamped to (380,180,400,200)
    ]}))
    a = ask(plan, DOORS)
    assert a.value == 2
    assert a.evidence[0].bbox == pytest.approx((10, 10, 40, 40)) and a.evidence[1].bbox == pytest.approx((380, 180, 400, 200))


def test_zero_objects_is_an_answer_not_a_failure(plan, provider):
    provider('{"detections": []}')
    a = ask(plan, WINDOWS)
    assert a.value == 0 and a.abstain is None and len(a.evidence) == 1 and a.evidence[0].bbox is None


def test_reply_with_prose_around_json_still_parses(plan, provider):
    provider("Here you go:\n```json\n" + dets((10, 10, 40, 40)) + "\n```")
    assert ask(plan, DOORS).value == 1


@pytest.mark.parametrize("reply", ["I see three doors.", "{not json}", '{"detections": "many"}', '[1,2]', ""])
def test_unparseable_reply_abstains_instead_of_answering_zero(plan, provider, reply):
    provider(reply)
    a = ask(plan, DOORS)
    assert a.value is None and a.abstain == "declined" and "parsed" in a.note


@pytest.mark.parametrize("text", [
    "How many bedrooms are there on this floor plan?",
    "How many saunas are shown on this floor plan?",
    "Kuinka monta makuuhuonetta pohjapiirroksessa on?",
    "Who drew this?",
])
def test_unsupported_templates_decline_without_calling_the_provider(plan, provider, text):
    calls = provider(dets((10, 10, 40, 40)))
    a = ask(plan, text)
    assert a.value is None and a.abstain == "declined" and not calls


def test_finnish_door_question_is_detected(plan, provider):
    provider(dets((10, 10, 40, 40)))
    assert ask(plan, "Kuinka monta ovea tässä pohjapiirroksessa on?").value == 1


def test_prompt_names_the_object_and_coordinate_grid(plan, provider):
    calls = provider(dets())
    ask(plan, DOORS)
    text = calls[0][1]["content"][0]["text"]
    assert "door" in text and "0 to 1000" in text


def test_provider_error_abstains_with_its_message(plan, monkeypatch):
    def boom(*a, **k):
        raise llm.LLMError("request cap reached (5 live requests)")
    monkeypatch.setattr(llm, "chat", boom)
    a = ask(plan, DOORS)
    assert a.value is None and a.abstain == "declined" and "request cap reached" in a.note


# --- llm.chat config, cap and no-retry (openai client faked) ---

class FakeClient:
    made = []

    def __init__(self, **kw):
        FakeClient.made.append(kw)
        self.chat = self
        self.completions = self

    def create(self, **kw):
        class M:
            content = "ok"
        class C:
            message = M()
        class U:
            prompt_tokens, completion_tokens = 7, 3
        class R:
            choices = [C()]
            usage = U()
        return R()


@pytest.fixture
def live(monkeypatch, tmp_path):
    import openai
    FakeClient.made = []
    monkeypatch.setattr(openai, "OpenAI", FakeClient)
    monkeypatch.setattr(llm, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(llm, "_env", lambda: None)
    monkeypatch.setenv("STOA_LLM_API_KEY", "k")
    llm.reset_usage()
    return monkeypatch


def msg(i):
    return [{"role": "user", "content": f"m{i}"}]


def test_chat_never_retries_and_uses_call_time_config(live):
    live.setenv("STOA_LLM_BASE_URL", "https://example.test/v1")
    live.setenv("STOA_LLM_MODEL", "some/model")
    assert llm.chat(msg(0)) == "ok"
    assert FakeClient.made[0]["max_retries"] == 0 and FakeClient.made[0]["base_url"] == "https://example.test/v1"
    assert "1 calls" in llm.usage() and "7+3 tokens" in llm.usage()


def test_request_cap_stops_live_calls_but_cache_is_free(live):
    live.setenv("STOA_LLM_MAX_REQUESTS", "2")
    llm.chat(msg(1)); llm.chat(msg(2))
    with pytest.raises(llm.LLMError, match="request cap reached"):
        llm.chat(msg(3))
    assert llm.chat(msg(1)) == "ok"  # cached
    assert len(FakeClient.made) == 2


def test_missing_key_is_a_clear_error(live):
    live.delenv("STOA_LLM_API_KEY"); live.delenv("FEATHERLESS_API_KEY", raising=False)
    with pytest.raises(llm.LLMError, match="no API key"):
        llm.chat(msg(9))
