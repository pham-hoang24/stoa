"""Positioned OCR for raster views, mapped once into original-source pixels.

OCR is optional context for the model. A view's status says what happened:
`ok` (words found), `empty` (engine ran, no words), `unavailable` (engine failed, never read as empty),
`skipped` (time budget spent) or `disabled`. None of these ever licenses "no object on the drawing".
"""
import hashlib
import math
import unicodedata
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
    # Every usable word (not only the prompt's top-scored subset) can tighten an evidence box.
    snap = [{'text': t['text'], 'confidence': t['confidence'], 'source_bbox': to_source(t['bbox'], descriptor['transform']),
             'view_id': descriptor['id']} for t in raw
            if t['confidence'] is None or t['confidence'] >= MIN_CONFIDENCE]
    record = {**record, 'status': 'ok' if raw else 'empty', 'tokens': tokens, 'tokens_total': total, '_snap': snap,
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
    return {'engine': ocr.ENGINE, 'review_status': 'unreviewed',
            'views': [{k: v for k, v in r.items() if not k.startswith('_')} for r in records]}


def _norm(text):
    """Casefolded letters and digits with accents folded (OCR often reads 'Küche' as 'Kuche')."""
    decomposed = unicodedata.normalize('NFKD', str(text).casefold())
    return ''.join(c for c in decomposed if c.isalnum() and not unicodedata.combining(c))


def _matches(word, target):
    return word == target or (len(word) >= 3 and len(target) >= 3 and (word in target or target in word))


def snap_evidence(evidence, records):
    """Tighten a model's box around printed text to the OCR words that spell it.

    Only words near the model's box are considered, the nearest match is taken per printed word,
    and at least half of the printed characters must be found. The model box is kept as model_bbox
    and the result is marked bbox_source 'ocr'; otherwise the evidence is left unchanged."""
    words = [t for r in records for t in r.get('_snap', []) if _norm(t['text'])]
    if not words:
        return
    for ev in evidence:
        box, text = ev.get('bbox'), ev.get('printed_text')
        if not box or not text or 'coverage' in ev or 'polygon' in ev:
            continue
        targets = [w for w in (_norm(part) for part in str(text).split()) if w]
        total = sum(len(t) for t in targets)
        if not total:
            continue
        w, h = box[2]-box[0], box[3]-box[1]
        pad = max(10, .5*min(w, h))
        cx, cy = (box[0]+box[2])/2, (box[1]+box[3])/2
        near = [t for t in words
                if box[0]-pad <= (t['source_bbox'][0]+t['source_bbox'][2])/2 <= box[2]+pad
                and box[1]-pad <= (t['source_bbox'][1]+t['source_bbox'][3])/2 <= box[3]+pad
                and (not ev.get('view_id') or t['view_id'] == ev['view_id'])]
        def centre(t):
            b = t['source_bbox']; return (b[0]+b[2])/2, (b[1]+b[3])/2

        def gap(t, box):
            b = t['source_bbox']
            dx, dy = max(0, box[0]-b[2], b[0]-box[2]), max(0, box[1]-b[3], b[1]-box[3])
            overlap = min(b[3], box[3]) - max(b[1], box[1])
            if overlap > .5*min(b[3]-b[1], box[3]-box[1]):
                dx /= 3  # same text line: label and value may be separated by a wide column gap
            return math.hypot(dx, dy)
        # Anchor on the longest printed word nearest the model's box, then grow a compact cluster:
        # each further word must lie within a few text heights of what is already chosen.
        order = sorted(targets, key=len, reverse=True)
        chosen, found, cluster = [], 0, None
        for target in order:
            options = [t for t in near if _matches(_norm(t['text']), target) and t not in chosen]
            if cluster is not None:
                height = max(cluster[3]-cluster[1], 1)
                options = [t for t in options if gap(t, cluster) <= 3*height]
            if not options:
                continue
            best = min(options, key=lambda t: gap(t, cluster) if cluster else math.hypot(centre(t)[0]-cx, centre(t)[1]-cy))
            chosen.append(best)
            found += min(len(target), len(_norm(best['text'])))
            b = best['source_bbox']
            cluster = list(b) if cluster is None else [min(cluster[0], b[0]), min(cluster[1], b[1]), max(cluster[2], b[2]), max(cluster[3], b[3])]
        # Numbers (room numbers, scales, dimensions) are what distinguishes one label from its
        # neighbours, so every mostly-numeric printed word must be found.
        matched = {_norm(t['text']) for t in chosen}
        digits_ok = all(any(_matches(m, target) for m in matched) for target in targets
                        if sum(c.isdigit() for c in target) > len(target) / 2)  # '2.27', '1:200'; not 'm²' or 'A3'
        if not chosen or found < total/2 or not digits_ok:
            continue
        union = [min(t['source_bbox'][0] for t in chosen), min(t['source_bbox'][1] for t in chosen),
                 max(t['source_bbox'][2] for t in chosen), max(t['source_bbox'][3] for t in chosen)]
        if not (union[0] < union[2] and union[1] < union[3]):
            continue
        ev['model_bbox'] = box
        ev['bbox'] = union
        ev['bbox_source'] = 'ocr'
        ev['ocr_match'] = {'text': ' '.join(t['text'] for t in chosen), 'matched_fraction': round(min(1, found/total), 3)}


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
