"""Optional local OCR with literal text and boxes in the supplied image's pixel frame."""
from __future__ import annotations

import math
import shutil
import subprocess

import cv2
import numpy as np

ENGINE = 'tesseract'
DEFAULT_LANGUAGES = ('eng', 'fin')
PROBE_TIMEOUT_SECONDS = 5
OCR_TIMEOUT_SECONDS = 30
TSV_COLUMNS = ('level','page_num','block_num','par_num','line_num','word_num',
               'left','top','width','height','conf','text')


class OcrUnavailable(RuntimeError):
    """The engine could not produce usable OCR; never interpret this as no text."""


def _run(exe, *args, image=None):
    timeout = PROBE_TIMEOUT_SECONDS if image is None else OCR_TIMEOUT_SECONDS
    try:
        proc = subprocess.run([exe,*args], input=image, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise OcrUnavailable(f'tesseract timed out after {timeout} seconds') from exc
    except OSError as exc:
        raise OcrUnavailable('tesseract could not be started') from exc
    if proc.returncode != 0:
        raise OcrUnavailable(f'tesseract command failed (exit {proc.returncode})')
    try:
        return proc.stdout.decode('utf8')
    except UnicodeDecodeError as exc:
        raise OcrUnavailable('tesseract returned non-UTF-8 output') from exc


def _version(exe):
    words = _run(exe,'--version').split()
    if len(words)<2 or words[0].lower()!='tesseract':
        raise OcrUnavailable('tesseract returned invalid version information')
    return words[1]


def _installed_languages(exe):
    lines = _run(exe,'--list-langs').splitlines()
    if not lines or not lines[0].startswith('List of available languages'):
        raise OcrUnavailable('tesseract returned invalid language information')
    return {line.strip() for line in lines[1:] if line.strip()}


def extract_text(image_bytes: bytes, languages: list[str] | None = None) -> list[dict]:
    """Return literal words, finite scores and bounded boxes; no network or source transforms."""
    try:
        image = cv2.imdecode(np.frombuffer(image_bytes,np.uint8),cv2.IMREAD_UNCHANGED)
    except (cv2.error,TypeError,ValueError) as exc:
        raise ValueError('input is not a decodable image') from exc
    if image is None:
        raise ValueError('input is not a decodable image')
    height,width = image.shape[:2]
    # A PNG transport removes EXIF orientation ambiguity without rotating pixels.
    ok,encoded = cv2.imencode('.png',image)
    if not ok:
        raise ValueError('input image cannot be encoded for OCR')
    if languages is not None and (not isinstance(languages,list) or not languages or
                                 any(not isinstance(code,str) or not code for code in languages)):
        raise ValueError('languages must be a nonempty list of language codes')
    langs = list(DEFAULT_LANGUAGES) if languages is None else languages
    exe = shutil.which(ENGINE)
    if exe is None:
        raise OcrUnavailable('tesseract binary not found on PATH; install tesseract to enable OCR')
    installed = _installed_languages(exe)
    unknown = [code for code in langs if code not in installed]
    if unknown:
        raise ValueError(f'OCR language not installed: {", ".join(unknown)}')
    version = _version(exe)
    text = _run(exe,'stdin','stdout','-l','+'.join(langs),'--psm','11','tsv',image=encoded.tobytes())
    lines = text.splitlines()
    if not lines or tuple(lines[0].split('\t'))!=TSV_COLUMNS:
        raise OcrUnavailable('tesseract returned invalid TSV output')
    tokens = []
    for line in lines[1:]:
        if not line.strip():continue
        fields = line.split('\t',11)
        try:
            if len(fields)!=12 or not 1<=int(fields[0])<=5:
                raise ValueError('invalid OCR row')
            if fields[0]!='5' or not fields[11].strip():continue
            x,y,w,h = map(int,fields[6:10])
            confidence = float(fields[10])
            if not (0<=x<x+w<=width and 0<=y<y+h<=height):
                raise ValueError('invalid OCR box')
            if not math.isfinite(confidence) or confidence>100:
                raise ValueError('invalid OCR confidence')
        except ValueError as exc:
            raise OcrUnavailable('tesseract returned invalid word coordinates or confidence') from exc
        tokens.append({'text':fields[11],'bbox':[x,y,x+w,y+h],
                       'confidence':None if confidence<0 else confidence,'engine':ENGINE,'version':version})
    return tokens
