# Local OCR adapter (issue #58) and chat integration (issue #62)

`stoa_chat.ocr.extract_text(image_bytes, languages=None)` returns positioned words from an image using the
local `tesseract` binary. It makes no network calls and adds no Python dependency.

```python
[{"text": "12,5", "bbox": [x0, y0, x1, y1], "confidence": 91.0, "engine": "tesseract", "version": "5.5.3"}]
```

- `bbox` is in the raw decoded pixel frame of the bytes you passed in. JPEG EXIF orientation is not applied; the adapter sends a PNG in that same frame to the engine. Converting to source-drawing coordinates is the caller's job.
- `text` is literal engine output: no case folding, no comma/dot normalisation, no dictionary correction.
- `confidence` is the engine's 0-100 word score, or `None` when the engine gives none. Callers should threshold it;
  real plans produce many low-confidence junk tokens from linework.
- `languages` defaults to `["eng", "fin"]`. A code that is not installed raises `ValueError` naming it.

## Failure states

| Situation | Result |
|---|---|
| Image has no recognisable text | `[]` |
| `tesseract` missing or failing | `OcrUnavailable` (never an empty list) |
| Bytes are not an image | `ValueError` |

Probe commands have a 5-second timeout; recognition has a 30-second timeout.
Startup errors, nonzero exits, timeouts, unusable metadata and malformed TSV output
raise `OcrUnavailable`. Word boxes must be nonempty and inside the input image;
scores must be finite and at most 100. Negative engine scores become `None`.
Invalid/empty image input and invalid language selections raise `ValueError`.
A missing language model is reported by name; ordinary English-only installations
can pass `languages=["eng"]` explicitly. Metadata probes run once each per call.

Tests that need the real engine skip when the required language data is unavailable; deterministic
contract tests still check failure handling and coordinate validity.

**An empty list means the engine ran and found no words. It never means "no object on the drawing";** missing OCR
text must not be used to declare an object absent.

## Known limits
- Page segmentation is sparse-text mode (`--psm 11`), which suits labels scattered over a plan. It reads upright
  text; rotated or upside-down labels need the page turned upright first (see `stoa.preprocess` orientation).
- On CubiCasa PNGs it misses many short labels (WC, MH) and reads linework as junk tokens. No accuracy has been
  measured; the small/rotated English and Finnish label comparison is still open.

## Chat integration (issue #62)

**Status: enabled by default, optional at runtime.** Raster (PNG/JPEG) questions run OCR when `tesseract` is on
`PATH`. Without it the VLM-only path runs unchanged and the answer says so. `STOA_OCR=off` disables OCR;
`STOA_OCR_LANGS=eng,fin` (default) picks languages. IFC, DXF, PDF and SVG never use OCR (they have native text).

- **Views read:** every `detail` tile and the single `page` view of an untiled image, in original pixels. The
  downscaled `overview` is not read. Each view is read once per question; no tile is dropped.
- **Coordinates:** each token keeps its input-crop `bbox` (what the model sees) and a `source_bbox` produced by that
  view's transform exactly once (`ocr_views.to_source`). Tokens also carry literal `text`, `confidence` (engine word
  score, not an answer probability), `engine`, `version`, `view_id` and `source_sha256`.
- **Model input:** payload `ocr` lists per-view `status` and up to 100 tokens (score >= 30, best first, then reading
  order) with `tokens_total`/`tokens_omitted` so truncation is visible. OCR is an unreviewed hint for candidate labels
  and printed dimensions/units. Counts and measurements still need the model's cited facts, Python validation
  (printed value + unit, ownership cores, full coverage) and Python arithmetic.
- **Answer:** `answer.ocr.views[]` records every view's status; `evidence[].ocr_support` lists OCR words inside each
  cited box, deduplicated by source location (overlapping tiles collapse, repeated labels at other places stay).
  Extra keys only; the inspector's evidence contract is unchanged.
- **Status values:** `ok` (words), `empty` (engine ran, found nothing), `unavailable` (missing/failed/timed out,
  with `error`), `skipped` (240 s per-question budget spent) and `disabled`. Only `empty` means the engine saw no text,
  and even then it never implies an absent object; count coverage comes from the tiles, not from OCR.
- **Cache:** in-process, keyed by view pixels, source hash, view id, transform, languages and the engine binary
  (path + mtime). Failures are never cached.

### Measured on this machine (Tesseract 5.5, eng+fin, synthetic renders, not real plans)
| Case | Result |
|---|---|
| Large English / Finnish labels (`Bedroom 12,5 m`, `Makuuhuone 12,5 m`) | read correctly, scores 91-96 |
| Small labels (~10 px glyphs) | `MH` read; `WC` read as `we`; `12,5 m` read as `125m` (comma and space lost) |
| Text rotated 90 degrees | nothing returned (`empty`) |

So small and rotated labels are unreliable, and decimal commas can vanish: the model must verify OCR against the
image and Python still requires the cited `printed_text` to contain the value and unit. No accuracy figure on real
drawings has been measured yet.
