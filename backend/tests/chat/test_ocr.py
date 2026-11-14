"""Behaviour of stoa_chat.ocr.extract_text: positioned literal text from a local engine, no network.

Fixtures are rendered with cv2 onto a white page; boxes are checked against where the text was drawn.
"""
import re
import shutil

import cv2
import numpy as np
import pytest

from stoa_chat.ocr import extract_text

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")


def page(*words, size=(1000, 300)):
    """White page, black text; each word is (text, (x, y_baseline)). Returns PNG bytes."""
    w, h = size
    img = np.full((h, w, 3), 255, np.uint8)
    for text, org in words:
        cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 4)
    ok, png = cv2.imencode(".png", img)
    assert ok
    return png.tobytes()


@needs_tesseract
def test_token_carries_literal_text_and_a_box_in_input_pixels():
    tokens = extract_text(page(("KITCHEN", (100, 150))))
    token = next(t for t in tokens if t["text"] == "KITCHEN")
    x0, y0, x1, y1 = token["bbox"]
    # the word was drawn from x=100 with a baseline at y=150, about 36px cap height
    assert 80 <= x0 <= 120 and x1 >= 300 and 90 <= y0 <= 130 and 140 <= y1 <= 170
    assert token["engine"] == "tesseract"
    assert re.match(r"\d+\.\d+", token["version"])
    assert token["confidence"] is None or 0 <= token["confidence"] <= 100


def test_missing_engine_is_an_explicit_error_not_an_empty_result(monkeypatch):
    from stoa_chat import ocr
    monkeypatch.setattr(ocr.shutil, "which", lambda name: None)
    with pytest.raises(ocr.OcrUnavailable, match="tesseract"):
        extract_text(page(("KITCHEN", (100, 150))))


@needs_tesseract
def test_bytes_that_are_not_an_image_are_rejected():
    with pytest.raises(ValueError, match="image"):
        extract_text(b"definitely not a png")


@needs_tesseract
def test_unknown_language_is_rejected_by_name():
    with pytest.raises(ValueError, match="klingon"):
        extract_text(page(("KITCHEN", (100, 150))), languages=["eng", "klingon"])


@needs_tesseract
def test_a_blank_page_has_no_tokens():
    assert extract_text(page()) == []


@needs_tesseract
def test_dimensions_and_finnish_labels_come_back_exactly_as_printed():
    png = page(("MAKUUHUONE", (30, 100)), ("12,5", (30, 200)), ("3.5x4.2", (800, 200)), ("KPH/WC", (900, 100)), size=(1400, 300))
    texts = {t["text"] for t in extract_text(png)}
    assert {"MAKUUHUONE", "12,5", "3.5x4.2", "KPH/WC"} <= texts
