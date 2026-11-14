"""Positioned OCR for raster views, mapped once into original-source pixels.

OCR is optional context for the model. A view's status says what happened:
`ok` (words found), `empty` (engine ran, no words), `unavailable` (engine failed, never read as empty),
`skipped` (time budget spent) or `disabled`. None of these ever licenses "no object on the drawing".
"""
import hashlib
import os
import shutil
import time
from collections import OrderedDict
from . import ocr

MAX_TOKENS_PER_VIEW = 100   # passed to the model and kept as evidence; the rest are counted, not hidden
MIN_CONFIDENCE = 30         # engine word score; linework junk sits below this
BUDGET_SECONDS = 240        # per drawing question; remaining views are reported as skipped
CACHE_SIZE = 256
_cache = OrderedDict()


def enabled():
    return os.environ.get('STOA_OCR', 'on').strip().lower() not in {'0', 'off', 'false', 'no'}


def languages():
    configured = [c.strip() for c in os.environ.get('STOA_OCR_LANGS', '').split(',') if c.strip()]
    return configured or list(ocr.DEFAULT_LANGUAGES)


def _engine_stamp():
    exe = shutil.which(ocr.ENGINE)
    try:
        return (exe, os.stat(exe).st_mtime_ns) if exe else None
    except OSError:
        return (exe, None)


def to_source(box, transform):
    """View pixels to original-source pixels: the single place this mapping happens."""
    sx, _, _, sy, tx, ty = transform
    return [box[0]*sx+tx, box[1]*sy+ty, box[2]*sx+tx, box[3]*sy+ty]


def bound(tokens):
    """Highest-scoring words first, then reading order; unscored words are kept below scored ones."""
    usable = [t for t in tokens if t['confidence'] is None or t['confidence'] >= MIN_CONFIDENCE]
    usable.sort(key=lambda t: -(t['confidence'] if t['confidence'] is not None else -1))
    return sorted(usable[:MAX_TOKENS_PER_VIEW], key=lambda t: (t['bbox'][1], t['bbox'][0])), len(tokens)


def read_view(image_bytes, descriptor, source_sha256, context):
    """OCR one view. Returns a status record; tokens carry view-pixel and source-pixel boxes."""
    record = {'view_id': descriptor['id'], 'status': 'ok', 'engine': ocr.ENGINE, 'languages': languages(),
              'source_sha256': source_sha256, 'tokens': [], 'tokens_total': 0, 'tokens_omitted': 0}
    if not enabled():
        return {**record, 'status': 'disabled'}
    deadline = context.setdefault('_ocr_deadline', time.monotonic() + BUDGET_SECONDS)
    key = (hashlib.sha256(image_bytes).hexdigest(), source_sha256, descriptor['id'],
           tuple(descriptor['transform']), tuple(record['languages']), _engine_stamp())
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    if time.monotonic() > deadline:
        return {**record, 'status': 'skipped', 'error': 'OCR time budget spent before this view'}
    try:
        raw = ocr.extract_text(image_bytes, record['languages'])
    except (ocr.OcrUnavailable, ValueError) as exc:
        return {**record, 'status': 'unavailable', 'error': str(exc)[:200]}
    kept, total = bound(raw)
    tokens = [{'id': f'{descriptor["id"]}#ocr{i}', 'text': t['text'], 'confidence': t['confidence'],
               'bbox': t['bbox'], 'source_bbox': to_source(t['bbox'], descriptor['transform']),
               'engine': t['engine'], 'version': t['version'], 'view_id': descriptor['id'],
               'source_sha256': source_sha256} for i, t in enumerate(kept)]
    record = {**record, 'status': 'ok' if raw else 'empty', 'tokens': tokens, 'tokens_total': total,
              'tokens_omitted': total - len(tokens), **({'version': raw[0]['version']} if raw else {})}
    _cache[key] = record
    while len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)
    return record


def prompt_block(records):
    """What the model sees: literal words and view-pixel boxes, plus every view's status."""
    return {'engine': ocr.ENGINE, 'review_status': 'unreviewed',
            'note': 'Engine word scores are not answer probabilities. Missing or empty OCR never means an object is absent.',
            'views': [{'view_id': r['view_id'], 'status': r['status'],
                       **({'error': r['error']} if r.get('error') else {}),
                       'tokens_total': r['tokens_total'], 'tokens_omitted': r['tokens_omitted'],
                       'tokens': [{'id': t['id'], 'text': t['text'], 'bbox': t['bbox'],
                                   'confidence': t['confidence']} for t in r['tokens']]} for r in records]}


def summary(records):
    return {'engine': ocr.ENGINE, 'review_status': 'unreviewed', 'views': records}


def _overlap(a, b):
    x = max(0, min(a[2], b[2])-max(a[0], b[0])); y = max(0, min(a[3], b[3])-max(a[1], b[1]))
    inter = x*y
    union = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter
    return inter/union if union else 0


def attach_support(evidence, records):
    """Link each visual evidence box to the OCR words inside it, deduplicated by source location.

    Overlapping tiles can read the same word twice; those collapse by position (keeping the higher
    score). Repeated labels at different positions stay separate, whatever their text."""
    tokens = sorted((t for r in records for t in r['tokens']),
                    key=lambda t: -(t['confidence'] if t['confidence'] is not None else -1))
    unique = []
    for t in tokens:
        if all(_overlap(t['source_bbox'], u['source_bbox']) < .5 for u in unique):
            unique.append(t)
    for ev in evidence:
        box = ev.get('bbox')
        if not box or 'coverage' in ev:
            continue
        inside = [t for t in unique if box[0] <= (t['source_bbox'][0]+t['source_bbox'][2])/2 <= box[2]
                  and box[1] <= (t['source_bbox'][1]+t['source_bbox'][3])/2 <= box[3]
                  and (not ev.get('view_id') or t['view_id'] == ev['view_id'])]
        if inside:
            ev['ocr_support'] = [{k: t[k] for k in ('id', 'text', 'confidence', 'source_bbox', 'view_id',
                                                    'engine', 'version', 'source_sha256')} for t in inside]
