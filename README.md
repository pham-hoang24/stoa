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

Native IFC quantities/inventories, DXF geometry with declared units and supported
PDF/SVG facts can work without a provider. Visual extraction and general question
interpretation use the server's configured OpenAI-compatible transport: set
`STOA_LLM_API_KEY` (or `FEATHERLESS_API_KEY`), `STOA_LLM_BASE_URL` and
`STOA_LLM_MODEL` in the environment or local `.env`. `STOA_LLM_MAX_REQUESTS`
bounds live calls; responses cache in `.cache/llm/`. Keys never reach the browser.
Missing keys, caps and outages produce explicit abstentions.

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
