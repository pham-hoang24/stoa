# Opening Design schedules (#14)

The `opening_design` source now uses the `schedules` lane. It reads selectable
text and vector table lines, computes counts/areas in code, and returns a PDF
page region for every contributing row. It does not use reference answers,
OCR, layout-model inference, or a hosted model. Unsupported geometry questions
and scans return typed `declined` abstentions instead of generic LLM guesses.

## Supported scope

- Individual door rows: counts by printed type, room, material, frame,
  notes and dimensions; specific scheduled dimensions/material/hardware fields.
- Weighted door-type schedules: sum the printed Count column, not the number
  of rows. Descriptor/floor selections use printed schedule text.
- Window schedules: count assemblies, select printed type marks, and expand
  N-wide assemblies into individual units only when explicitly requested.
- Finish room schedules: count listed rows, read/sum printed square-foot
  areas, select finish codes and room labels, and read finish-key definitions.
  Missing areas prevent a total unless the question explicitly limits scope to
  entries with listed areas. Feet-inch dimension strings remain unchanged.

This is a bounded parser for native schedule tables, not general construction
drawing interpretation. Unknown attributes, missing/duplicate identifiers,
ambiguous merged rows, unavailable filter columns, invalid quantities, conflicting legends and requested
metric conversions abstain. Region geometry never establishes a fixture count:
the three A-701 restroom-plan questions are deliberately outside this lane.

## Extraction and evidence

The PDFs use 90-degree page rotation. Rotation is removed in memory without
writing to the source, so table boxes are in the same displayed-page coordinate
system used by the viewer: top-left origin, 72 points per inch, zero-based page.
Evidence references are relative to the configured dataset root.

PyMuPDF 2.1 enables layout-model detection by default in `find_tables`. This
lane explicitly disables it when that option exists; older versions already
use line-based extraction. Only native PDF text and vector lines are read.
Matching headers and separated table bodies are joined by column alignment
and proximity. A merged row is split only when each printed identifier has an
unambiguous value in every mapped field. Neighboring diagram captions are
bounded separately so a door-type description cannot absorb the next type.

Extraction is cached by resolved path, modification time and size. Counting
does not change the cached table data. Source filenames and building identities
are not a lookup table for answers.

## Measurements

The preview/full question set for this source is the same small cohort: 64
questions over three sheets from two projects. There is no held-out result or
claim of generalization from this cohort.

| Cohort | Result |
|---|---:|
| All questions, existing local grader | 60/64 (93.8%) |
| Questions with a source-backed schedule answer | 61/64 |
| Fixture-plan questions deliberately declined | 3/64 |
| Count questions | 37/39; the two misses are declined fixture-plan counts |
| Square-foot area questions | 9/9 |
| Hosted calls for the full deterministic pass | 0 |
| Full deterministic pass, including cold table extraction | about 2.9 s |

The remaining graded miss is the literal printed frame code `HM`. The
reference says `HM (hollow metal)`; the existing text scorer rejects the
returned code because the reference has no numbers. This lane preserves the
printed value rather than inserting an expansion absent from the parsed
legend. Text scores use that legacy proxy and are not semantic accuracy.

Key independently checked quantities include 38 door identifiers, 29 finish
room rows (including unmeasured redundant-room entries), 49,560 SF of listed
room areas, 657 weighted door-type items, 235 window assemblies, and 379
explicitly expanded window units. The parsed door and window Count columns
are independent inventories and are never combined as duplicate rows.

### Bounded live baseline

Before the routing change, the generic LLM lane was measured on three count
questions, one per drawing: source-order indices 0, 41 and 44. The transport
was capped at three requests, with no retries and a 45-second timeout. All
requests completed in 19.6 seconds. Provider usage was 62,000 tokens and
$0.009307. The original lane scored 2/3 on this smoke cohort; the schedule lane
answers the two schedule cases and explicitly declines the restroom case.
This tiny cohort is not a full LLM baseline or a held-out comparison.

## Validation and demo decision

Router-boundary and independent PDF fixtures cover weighted counts, zero
matches, source-only parsing, feet-inch values, dimension/description filters,
missing quantities, duplicate identifiers, missing areas, merged room rows,
explicit window expansion, wrong-sheet scope, raster pages with vector title
blocks, and rotated-page evidence opening in the viewer. Real-sheet tests
exercise both native schedule layouts and page-region evidence.

Implementation choice: retain native schedules as an optional supplemental
lane. The original three-path demo remains Swiss, IFC and raster vision. No
fixture-plan interpretation or new prepared UI example is added here; the team
lead retains the decision about exposing this optional lane in the demo.

Reproduce with:

```bash
STOA_DATASET=data/junction-dataset-preview .venv/bin/python -m stoa.eval.run --source opening_design --dump /tmp/schedules.jsonl
STOA_DATASET=data/junction-dataset-preview .venv/bin/python -m pytest tests/test_schedules.py -q
STOA_DATASET=data/junction-dataset-preview make check
```
