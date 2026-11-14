# Local OCR adapter (issue #58)

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

The adapter is not wired into chat extraction yet. Install the local Tesseract
binary and desired `eng`/`fin` language data before using it. Tests that need the
real engine skip when the required language data is unavailable; deterministic
contract tests still check failure handling and coordinate validity.

**An empty list means the engine ran and found no words. It never means "no object on the drawing";** missing OCR
text must not be used to declare an object absent.

## Known limits
- Page segmentation is sparse-text mode (`--psm 11`), which suits labels scattered over a plan. It reads upright
  text; rotated or upside-down labels need the page turned upright first (see `stoa.preprocess` orientation).
- On CubiCasa PNGs it misses many short labels (WC, MH) and reads linework as junk tokens. No accuracy has been
  measured; the small/rotated English and Finnish label comparison is still open.
