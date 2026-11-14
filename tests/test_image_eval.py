"""Workflow/scoring mechanics on controlled fixtures, not vision accuracy."""
import copy
import json

import pytest

from stoa.image_eval import annotation_page, initialize, match_boxes, run, validate_manifest
from test_image_runtime import image, reply


def labelled(tmp_path):
    (tmp_path / "private plan.png").write_bytes(image())
    manifest = initialize(tmp_path, "private project", "test")
    for case in manifest["cases"]:
        case.update(boxes=[[20, 12, 40, 24]], annotator="Independent annotator")
    return manifest


def test_init_is_unlabelled_and_offline_page_embeds_only_pixels_and_annotations(tmp_path):
    (tmp_path / "drawing.png").write_bytes(image())
    (tmp_path / "renamed.png").write_bytes(image())
    manifest = initialize(tmp_path, "group </script>", "test")
    assert len(manifest["cases"]) == 2  # one image, two distinct targets
    assert all(c["boxes"] is None and not c["annotator"] for c in manifest["cases"])
    page = annotation_page(manifest)
    assert "data:image/png;base64," in page and "/*ANNOTATION_DATA*/null" not in page
    assert "group </script>" not in page and "group \\u003c/script>" in page
    assert "fetch(" not in page and "/api/image-questions" not in page
    with pytest.raises(ValueError):
        validate_manifest(manifest)


@pytest.mark.parametrize("change,expected", [
    (lambda m: m["cases"][0].update(label_origin="model_assisted_correction"), "Independent manual"),
    (lambda m: m["cases"][0].update(annotator=""), "Independent manual"),
    (lambda m: m["cases"][0].update(digest="wrong"), "changed"),
    (lambda m: m["cases"][1].update(split="dev"), "both dev and test"),
    (lambda m: m["cases"][1].update(project="another"), "Identical pixels"),
    (lambda m: m["cases"].append(copy.deepcopy(m["cases"][0])), "Duplicate"),
])
def test_label_origin_group_and_pixel_identity_guards(tmp_path, change, expected):
    manifest = labelled(tmp_path)
    change(manifest)
    with pytest.raises(ValueError, match=expected):
        validate_manifest(manifest)


def test_reference_changes_do_not_change_inference_inputs(tmp_path):
    manifest = labelled(tmp_path)
    calls = []
    def detector(view, task):
        calls.append((view.png, task))
        return reply([[100, 100, 200, 200]])
    first = run(manifest, detect=detector)
    original_calls = calls[:]
    for case in manifest["cases"]:
        case["boxes"] = []
    calls.clear()
    second = run(manifest, detect=detector)
    assert calls == original_calls
    assert first["tp"] == 2 and first["exact_count_accuracy"] == 1
    assert second["fp"] == 2 and second["exact_count_accuracy"] == 0


def test_request_budget_and_abstentions_remain_in_denominator(tmp_path):
    manifest = labelled(tmp_path)
    calls = []
    report = run(manifest, request_budget=1, detect=lambda *args: calls.append(1) or reply([[100, 100, 200, 200]]))
    assert len(calls) == report["inspection_requests"] == 1
    assert report["cases"] == 2 and report["answered"] == report["abstentions"] == 1
    assert report["recall"] == report["exact_count_accuracy"] == 0.5
    declined = run(manifest, detect=lambda *args: "not valid JSON")
    assert declined["fn"] == 2 and declined["answered"] == 0 and declined["recall"] == 0


def test_matching_is_one_to_one_and_finds_augmenting_path():
    # The first prediction can match either reference; the second only the first.
    references = [(0, 0, 10, 10), (8, 0, 18, 10)]
    proposals = [(0, 0, 18, 10), (0, 0, 9, 10)]
    assert match_boxes(proposals, references, 0.5) == (2, 0, 0)
    assert match_boxes(proposals + [proposals[1]], references, 0.5) == (2, 1, 0)
    assert match_boxes([], references) == (0, 0, 2)
