"""Local OCR adapter: positioned literal text from an image, with no network access.

`extract_text` returns JSON-ready tokens whose boxes are in the pixels of the image it was given.
Converting to source-drawing coordinates is the caller's job, not this module's.
"""
from __future__ import annotations

import shutil
import subprocess

import cv2
import numpy as np

ENGINE = "tesseract"


class OcrUnavailable(RuntimeError):
    """The local OCR engine is not installed or could not run. Never read as 'no text on the image'."""


def _version(exe: str) -> str:
    out = subprocess.run([exe, "--version"], capture_output=True, text=True).stdout
    return out.split()[1] if out.split()[1:] else ""


DEFAULT_LANGUAGES = ("eng", "fin")  # the drawings are Finnish with English questions; callers can narrow this


def _installed_languages(exe: str) -> set[str]:
    out = subprocess.run([exe, "--list-langs"], capture_output=True, text=True).stdout
    return {line.strip() for line in out.splitlines()[1:] if line.strip()}


def extract_text(image_bytes: bytes, languages: list[str] | None = None) -> list[dict]:
    """Words found in the image: {text, bbox [x0, y0, x1, y1], confidence (0-100 or None), engine, version}."""
    exe = shutil.which("tesseract")
    if exe is None:
        raise OcrUnavailable("tesseract binary not found on PATH; install tesseract to enable OCR")
    langs = list(languages) if languages else list(DEFAULT_LANGUAGES)
    unknown = [code for code in langs if code not in _installed_languages(exe)]
    if unknown:
        raise ValueError(f"OCR language not installed: {', '.join(unknown)}")
    if cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR) is None:
        raise ValueError("input is not a decodable image")
    proc = subprocess.run([exe, "stdin", "stdout", "-l", "+".join(langs), "--psm", "11", "tsv"],
                          input=image_bytes, capture_output=True)
    if proc.returncode != 0:
        raise OcrUnavailable(f"tesseract failed: {proc.stderr.decode('utf8', 'replace').strip()[:200]}")
    version = _version(exe)
    tokens = []
    for line in proc.stdout.decode("utf8", "replace").splitlines()[1:]:
        f = line.split("\t")
        if len(f) < 12 or f[0] != "5" or not f[11].strip():
            continue
        x, y, w, h, conf = int(f[6]), int(f[7]), int(f[8]), int(f[9]), float(f[10])
        tokens.append({"text": f[11], "bbox": [x, y, x + w, y + h], "confidence": None if conf < 0 else conf,
                       "engine": ENGINE, "version": version})
    return tokens
