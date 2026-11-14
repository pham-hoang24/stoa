# Local OCR adapter (issue #58)

`stoa_chat.ocr.extract_text(image_bytes, languages=None)` returns positioned words from an image using the
local `tesseract` binary. It makes no network calls and adds no Python dependency.

```python
[{"text": "12,5", "bbox": [x0, y0, x1, y1], "confidence": 91.0, "engine": "tesseract", "version": "5.5.3"}]
```

- `bbox` is in the pixels of the bytes you passed in. Converting to source-drawing coordinates is the caller's job.
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

**An empty list means the engine ran and found no words. It never means "no object on the drawing";** missing OCR
text must not be used to declare an object absent.

## Known limits
- Page segmentation is sparse-text mode (`--psm 11`), which suits labels scattered over a plan. It reads upright
  text; rotated or upside-down labels need the page turned upright first (see `stoa.preprocess` orientation).
- On CubiCasa PNGs it misses many short labels (WC, MH) and reads linework as junk tokens. No accuracy has been
  measured; the small/rotated English and Finnish label comparison is still open.
