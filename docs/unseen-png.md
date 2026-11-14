# Unseen PNG workflow (issue #36)

The application boundary takes validated PNG pixels and a supported task. It has
no benchmark question ID, source directory, expected answer or reference boxes.
Current support is whole-image window symbols and individual door leaves. Bare
“doors” asks for confirmation because openings and leaves differ. Unsupported
filters, measurements and scopes decline rather than silently count everything.

## Upload and review preview

```sh
.venv/bin/stoa serve
# Open http://127.0.0.1:8765/upload

.venv/bin/stoa ask '/path/to/new floor plan.png' 'Count all visible windows'
.venv/bin/stoa ask '/path/to/new floor plan.png' 'Count doors' --confirm-target door_leaf
```

Choose a PNG from any folder. The server validates the contents and stores a
normalized copy in `.cache/uploads`; paths and image metadata never enter the
model request. Equivalent pixels share an ID even after renaming or re-encoding.
The preview binds only to loopback. Images remain until this local cache is
removed. Assessment history is bounded and expires when the server restarts.

Live inspection uses the bounded transport from PR #29, whose original commits
are included in this feature branch. Set `STOA_LLM_MAX_REQUESTS`
to a small process cap when using that transport; the application also preflights
complete crop coverage against a maximum of nine inspection requests per task.
No automatic retries occur. Invalid replies, incomplete coverage, uncertain
candidates and ambiguous overlaps decline with proposed evidence retained.

When inspection is unavailable you can still draw and review boxes manually.
Every machine count is labelled unreviewed, including zero. Coordinates and SVG
overlays use original source pixels. Save a reviewed count only after inspecting
the full image. Downloads preserve the original machine result separately from
the reviewer’s corrections; these corrections are model-assisted labels.

The shared viewer mounts `UploadAPI.handle(handler)` routes:
`/upload`, `/api/uploads`, `/api/assets/<id>`, `/api/image-questions` and
`/api/image-reviews`. Dataset examples remain at `/`. Explicit existing local PNG
paths bypass benchmark routing even when their filenames or directories resemble
a different source. Benchmark-relative paths retain their benchmark adapters.
For a separate integration preview, `python -m stoa.upload_api` serves the same
upload routes on port 8091. Both entry points use the same asset store.

## Independent evaluation

Start with PNGs that have not informed implementation or prompt development.
Keep every floor/view/variant of one project or design in the same split. Pixel
hashes detect exact duplicates; humans must supply accurate project groups for
related drawings that differ in pixels.

```sh
.venv/bin/python -m stoa.image_eval init /path/to/new-project \
  --project project-unique-id --split test --output /tmp/project-labels.json
```

Open the generated `/tmp/project-labels.html`. This offline page shows no model
proposals and makes no model calls. Draw independent boxes, identify the
annotator, inspect the complete image for each target and download the completed
manifest. To evaluate multiple projects together, concatenate their case lists
into a version-1 manifest. Paths remain local and must still point to the same
pixels when scoring. Both dev and test cases may be included; the scorer rejects
overlapping project groups or pixel identities across splits.

```sh
.venv/bin/python -m stoa.image_eval run /tmp/independent-labels.json \
  --split test --limit 5 --max-requests 10 --output /tmp/png-report.json
```

The scorer rejects model-assisted corrections and unlabelled cases. Only pixels
and canonical tasks enter inference. Reference boxes are used afterward for
one-to-one localization matching at IoU ≥ 0.5, exact counts, precision/recall,
abstentions and latency. Abstained/budget-exhausted cases remain in count accuracy
and recall denominators. Inspection requests are reported separately from shared
provider usage snapshots (live calls, cache hits and tokens). An abstained task’s
candidate boxes remain in its record but are not accepted detections.

No independently annotated unseen cohort has been supplied yet. Automated tests
use controlled fixtures and stubbed providers to verify boundaries, geometry and
failure handling. They establish **no perception accuracy or generalization**.
Do not select prompts on the test split or claim generality from a small cohort.
