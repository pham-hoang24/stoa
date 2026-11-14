"""Synthetic integration checks; these do not measure perception accuracy."""
import json
import struct

import cv2
import numpy as np
import pytest

from stoa import data
from stoa.assets import AssetStore, DrawingError, from_bytes, from_path
from stoa.detection_geometry import Detection, View, deduplicate, project, views
from stoa.image_review import review
from stoa.image_runtime import assess
from stoa.image_task import CountTask, interpret


def image(width=200, height=120, blank=False):
    pixels = np.full((height, width, 3), 255, np.uint8)
    if not blank:
        cv2.rectangle(pixels, (20, 20), (width - 20, height - 20), (0, 0, 0), 2)
    return cv2.imencode(".png", pixels)[1].tobytes()


def reply(boxes=(), **kwargs):
    return json.dumps({"readable": True, "complete": True,
                       "detections": [{"box": b, "uncertain": False} for b in boxes], **kwargs})


def test_external_file_and_renamed_pixels_have_the_same_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "ROOT", tmp_path / "missing-benchmark")
    monkeypatch.setattr(data, "load_questions", lambda: pytest.fail("application must not read reference records"))
    path = tmp_path / "new drawing with spaces.bin"
    path.write_bytes(image())
    drawing = from_path(path)
    other = tmp_path / "cubicasa5k" / "four windows.png"
    other.parent.mkdir()
    other.write_bytes(path.read_bytes())
    assert from_path(other).id == drawing.id
    calls = []
    detector = lambda view, task: calls.append((view.png, task)) or reply([[100, 100, 200, 200]])
    first = assess(drawing, "How many windows are visible?", detect=detector)
    second = assess(from_path(other), "Please count all windows", detect=detector)
    assert first.answer.value == second.answer.value == 1
    assert calls[0] == calls[1]
    assert first.answer.evidence[0].bbox == (20, 12, 40, 24)


@pytest.mark.parametrize("question", [
    "How many windows are there?", "Count the windows", "Show me every visible window",
    "Tell me the number of windows in this picture", "Please locate all windows on the drawing",
])
def test_count_wording_does_not_require_a_benchmark_template(question):
    decision = interpret(question)
    assert decision.status == "ready" and decision.task.target == "window"


@pytest.mark.parametrize("question", [
    "How many red windows?", "Count windows with red frames", "Count windows in the kitchen",
    "Count windows on the left", "What color are the windows?", "What is the area in m2?",
    "Count door openings", "Count only windows on the first floor",
    "Count windows and balconies", "Count windows beside stairs", "Count windows in the plan beside the entrance",
])
def test_unsupported_scope_properties_and_measurements_do_not_count_everything(question):
    result = assess(from_bytes(image()), question, detect=lambda *args: pytest.fail("unsupported question must not call a provider"))
    assert result.answer.value is None and result.status == "declined"


def test_door_unit_and_mixed_targets_need_explicit_confirmation():
    assert interpret("How many doors?").status == "clarification_required"
    assert interpret("How many doors and windows?").status == "clarification_required"
    assert interpret("How many doors?", "door_leaf").task == CountTask("door_leaf")
    assert interpret("How many windows?", "door_leaf").status == "declined"
    assert interpret("Count door leaves").status == "ready"


def test_blank_image_is_declined_without_a_prior_or_a_provider_call():
    result = assess(from_bytes(image(blank=True)), "How many windows?", detect=lambda *args: pytest.fail("blank image"))
    assert result.answer.value is None and "blank" in result.answer.note


@pytest.mark.parametrize("payload", [b"not a PNG", b"\x89PNG\r\n\x1a\n", image()[:33]])
def test_corrupt_image_is_rejected(payload):
    with pytest.raises(DrawingError):
        from_bytes(payload)


def test_dimensions_are_checked_before_decompression():
    payload = bytearray(image())
    payload[16:24] = struct.pack(">II", 1_000_000, 1_000_000)
    with pytest.raises(DrawingError, match="megapixel"):
        from_bytes(bytes(payload))


def test_store_serves_only_valid_content_ids_and_detects_replaced_bytes(tmp_path):
    store = AssetStore(tmp_path / "uploads")
    drawing = store.put(image())
    assert store.get(drawing.id).png == drawing.png
    with pytest.raises(DrawingError):
        store.get("../secret.png")
    (store.directory / f"{drawing.id}.png").write_bytes(image(width=220))
    with pytest.raises(DrawingError, match="changed"):
        store.get(drawing.id)


def test_crop_coordinates_map_to_source_and_duplicates_are_joined():
    first = project([300, 200, 500, 400], View("a", (0, 0, 100, 100), b""))
    second = project([100, 200, 300, 400], View("b", (20, 0, 120, 100), b""))
    kept, ambiguous = deduplicate([first, second])
    assert first.box == (30, 20, 50, 40) and len(kept) == 1 and not ambiguous


def test_crop_edge_fragment_can_join_a_full_detection():
    full = Detection((20, 20, 60, 60), "a")
    fragment = Detection((40, 20, 60, 60), "b", edge=True)
    assert deduplicate([full, fragment])[0] == (full,)


def test_overlapping_distinct_candidates_are_flagged_instead_of_guessed():
    _, ambiguous = deduplicate([Detection((10, 10, 50, 50), "a"), Detection((20, 10, 60, 50), "b")])
    assert ambiguous


def test_tiling_covers_edges_and_budget_is_checked_before_calls():
    drawing = from_bytes(image(300, 180))
    planned = views(drawing, tile_edge=160, overlap=40, max_requests=9)
    assert len(planned) == 7
    for y in range(drawing.height):
        for x in range(drawing.width):
            assert any(v.rect[0] <= x < v.rect[2] and v.rect[1] <= y < v.rect[3] for v in planned[1:])
    result = assess(drawing, "Count windows", tile_edge=160, overlap_pixels=40, max_requests=2,
                    detect=lambda *args: pytest.fail("budget must be checked before sending"))
    assert result.answer.value is None and result.requests == 0


@pytest.mark.parametrize("text", [
    "I see four windows", "{bad JSON}", '{"detections":[]}',
    reply([[0, 0, 1001, 1000]]), reply([[500, 500, 100, 100]]),
    reply([[True, 0, 500, 500]]),
    '{"readable":true,"complete":true,"detections":[{"box":[1,2,3,4]}]}',
])
def test_invalid_detections_never_become_a_zero_count(text):
    result = assess(from_bytes(image()), "Count windows", detect=lambda *args: text)
    assert result.answer.value is None and result.answer.abstain == "declined"


def test_valid_empty_detection_list_is_an_unreviewed_zero():
    result = assess(from_bytes(image()), "Count windows", detect=lambda *args: reply())
    assert result.answer.value == 0 and result.status == "unreviewed"
    assert result.payload()["reviewed"] is False


def test_uncertain_or_incomplete_detector_output_declines():
    for text in [reply(complete=False), reply(readable=False),
                 json.dumps({"readable": True, "complete": True, "detections": [{"box": [100, 100, 200, 200], "uncertain": True}]})]:
        result = assess(from_bytes(image()), "Count windows", detect=lambda *args: text)
        assert result.answer.value is None


def test_provider_failure_does_not_retry_or_expose_its_secret():
    calls = []
    def broken(*args):
        calls.append(1)
        raise ValueError("secret-token")
    result = assess(from_bytes(image()), "Count windows", detect=broken)
    assert calls == [1] and result.answer.value is None
    assert "secret-token" not in json.dumps(result.payload())


def test_live_adapter_sends_only_pixels_and_task_and_requires_bounded_transport(monkeypatch):
    from stoa.image_runtime import ProviderUnavailable, provider
    from stoa.lanes import llm
    drawing = from_bytes(image())
    view = views(drawing)[0]
    monkeypatch.delattr(llm, "settings", raising=False)
    monkeypatch.setattr(llm, "chat", lambda *args, **kwargs: pytest.fail("unbounded transport must not run"))
    with pytest.raises(ProviderUnavailable):
        provider(view, CountTask("window"))
    captured = []
    monkeypatch.setattr(llm, "settings", lambda: {}, raising=False)
    monkeypatch.setattr(llm, "chat", lambda messages, **kwargs: captured.append((messages, kwargs)) or reply())
    assert provider(view, CountTask("window")) == reply()
    messages, options = captured[0]
    assert options["max_tokens"] == 4000
    assert messages[1]["content"][1] == llm.image_part(view.png)
    assert "each visible window symbol" in messages[1]["content"][0]["text"]


def test_user_review_does_not_mutate_or_masquerade_as_independent_labels():
    result = assess(from_bytes(image()), "Count windows", detect=lambda *args: reply([[100, 100, 200, 200]]))
    corrected = review(result, [], "Reviewer", True)
    assert corrected["review"]["count"] == 0
    assert corrected["review"]["label_origin"] == "model_assisted_correction"
    assert corrected["machine"]["answer"]["value"] == result.answer.value == 1
    with pytest.raises(ValueError, match="Confirm"):
        review(result, [], "Reviewer", False)
