# Stoa

Answers quantity-takeoff questions about construction drawings ("how many doors on this floor?", "area of room 2.05?") and shows the evidence behind each answer. Built for the Junction 2026 challenge. Terms are defined in [GLOSSARY.md](GLOSSARY.md); design decisions are in [docs/adr](docs/adr).

## Local drawing chatbot

Run `uv sync`, then `uv run stoa-chat` (or `make chat`) and open
http://127.0.0.1:8092. The dedicated buildless app lives in `frontend/`; the
existing pitch site in `web/` is independent. No frontend install or build is needed.
Python source and tests live in `backend/src/` and `backend/tests/`.

Create a conversation, upload several PNG, JPEG, PDF, IFC, DXF or SVG drawings,
select the relevant drawings, and ask a question. Follow-ups retain selected scope
and target context. Use source buttons to open a safe PNG page preview with
source-coordinate boxes, polygons or calibration lines, inspect native entity
IDs/properties and calculations, or open the original. Native entities without
spatial previews still expose their source properties. Delete removes a conversation
and uploads unreferenced by other conversations.

Chats and originals persist in `.cache/chat/` (SQLite plus content-addressed assets).
Use `uv run stoa-chat --storage /path/to/local-data --port 8092` to choose another
location, and `--frontend /path/to/frontend` to override the static app directory.
Run one process per storage directory. This local prototype has no accounts or
remote deployment configuration; it binds to `127.0.0.1`.

IFC uploads accept up to 512 MiB by default; other formats retain a 50 MiB limit.
For larger models, use `uv run stoa-chat --max-ifc-upload-mib 1024` (1 GiB).
The browser reads the active limits from the server. Restart the server and refresh
the page after changing the limit.

Native IFC quantities/inventories, DXF geometry with declared units and supported
PDF/SVG facts can work without a provider. Visual extraction defaults to NVIDIA:
`https://integrate.api.nvidia.com/v1`, model
`nvidia/nemotron-3.5-super-vl-120b-a12b`, authenticated with `NVIDIA_API_KEY`.
Keep credentials in the server environment or local `.env`; keys never reach the browser.

By default, a NVIDIA timeout falls through once to Modal. Choose the secondary provider:

```sh
uv run stoa-chat --llm-provider nvidia --llm-fallback modal
# Or: --llm-fallback featherless
```

The timeout defaults to **60 seconds per provider attempt**; override it with
`--llm-timeout-seconds 30`. Equivalent environment options are
`STOA_LLM_PROVIDER=nvidia`, `STOA_LLM_FALLBACK=modal`, and
`STOA_LLM_TIMEOUT_SECONDS=60`. Use fallback `none` to disable automatic fallthrough.
Only SDK timeouts or HTTP 408/504 activate fallback. Authentication errors,
rate limits, connection failures, HTTP 503 and other errors remain explicit.
A secondary timeout stops the chain; there are at most two live attempts.
Each attempt counts against `STOA_LLM_MAX_REQUESTS` (default 200 per process).
Cached replies remain free, separated by provider/endpoint/model; fallback results
are never cached as NVIDIA answers. Answer provenance identifies the actual
provider/model and records timeout fallthrough.

- NVIDIA uses `NVIDIA_API_KEY`; optional `STOA_NVIDIA_BASE_URL` and `STOA_NVIDIA_MODEL` override its preset.
- Modal uses `MODAL_API_KEY`, `https://uknowme1928--ep-stoa-server.us-west.modal.direct/v1`, and `Qwen/Qwen3.8-Max-VL-Thinking`. Override with `STOA_MODAL_BASE_URL` and `STOA_MODAL_MODEL`.
- Featherless uses `STOA_LLM_API_KEY` (or `FEATHERLESS_API_KEY`), with existing `STOA_LLM_BASE_URL` and `STOA_LLM_MODEL` overrides.

NVIDIA and Modal root endpoint URLs are normalized to `/v1`. Credentials and model
settings remain provider-specific, including on fallback. Missing keys never cause
silent credential reuse or fallthrough. Explicit `--llm-provider modal` or
`--llm-provider featherless` runs that provider directly without NVIDIA fallback.
Restart the server when changing CLI or `.env` settings.

Answers distinguish **native source support**, **unreviewed model proposals**,
**estimates**, **clarification**, **abstention** and **analysis errors**. Model
extraction supplies facts and regions; Python computes quantities. A quantity
needs adequate evidence, units and scale, with height for volume. Multiple drawing
totals require explicit independence confirmation; identical uploads are flagged.
The app does not promise arbitrary CAD reasoning or validated visual accuracy.
Controlled tests verify behavior and arithmetic; independent held-out perception
validation remains separate (#38).

Run `uv run pytest` (all backend tests), or `uv run pytest backend/tests/chat`
(the public chat HTTP seam). See [browser smoke instructions](frontend/README.md)
and the [API contract](backend/README.md). Legacy `stoa ask`, `stoa serve` and
benchmark evaluation remain available independently below. Dataset, `.env`,
`viewer/examples.json` and `.cache/` retain their repository-root meanings;
installed packages use the working directory unless `STOA_PROJECT_ROOT` is set.

## How it works

The router picks a lane from the drawing's source and format. Each lane returns an `Answer` with a value (or abstains), a unit and evidence.

| Lane | Drawings | Method |
|---|---|---|
| `ifc` | `ifc_models`, `ifc_bench` | IfcOpenShell: quantities and spatial structure |
| `swiss` | `swiss_dwellings` | Rules on the DXF sibling of each PDF, no LLM |
| `vision` | `cubicasa5k` PNGs | Vision model detects doors/windows; counting, dedup and numbering are done in code, no dataset priors |
| `doc` | everything else | LLM over page text and renders (`lanes/llm.py`) |

## Setup

Python 3.12 and [uv](https://docs.astral.sh/uv/).

```
uv sync
export STOA_DATASET=/path/to/junction-dataset   # defaults to ./dataset
echo "FEATHERLESS_API_KEY=..." > .env           # only the llm and vision lanes need it
```

## Use

```
stoa ask data/swiss_dwellings/<file>.pdf "How many doors are drawn on this floor plan?"
stoa serve                                       # click-to-verify viewer on :8765
stoa ask '/path/to/new floor plan.png' 'Count all visible windows'
python -m stoa.eval.run --lane swiss --show-wrong 20
make check                                       # tests + no-LLM accuracy gate (needs the dataset, no API key)
```

Open `http://127.0.0.1:8765/upload` to inspect your own PNG without installing a
dataset. Window and door-leaf counts remain unreviewed proposals until you inspect
the marked objects. [PNG workflow and independent evaluation](docs/unseen-png.md)
explain request limits, review corrections and current accuracy limitations.

## Team

The team coordinates through one pinned GitHub issue, the board. See [AGENTS.md](AGENTS.md).
