# Stoa

Answers quantity-takeoff questions about construction drawings ("how many doors on this floor?", "area of room 2.05?") and shows the evidence behind each answer. Built for the Junction 2026 challenge. Terms are defined in [GLOSSARY.md](GLOSSARY.md); design decisions are in [docs/adr](docs/adr).

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
