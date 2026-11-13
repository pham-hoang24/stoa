# Stoa

Answers quantity-takeoff questions about construction drawings ("how many doors on this floor?", "area of room 2.05?") and shows the evidence behind each answer. Built for the Junction 2026 challenge. Terms are defined in [GLOSSARY.md](GLOSSARY.md); design decisions are in [docs/adr](docs/adr).

## How it works

The router picks a lane from the drawing's source and format. Each lane returns an `Answer` with a value (or abstains), a unit and evidence.

| Lane | Drawings | Method |
|---|---|---|
| `ifc` | `ifc_models`, `ifc_bench` | IfcOpenShell: quantities and spatial structure |
| `swiss` | `swiss_dwellings` | Rules on the DXF sibling of each PDF, no LLM |
| `vision` | `cubicasa5k` PNGs | Vision model, with priors for templates where it is weak |
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
python -m stoa.eval.run --lane swiss --show-wrong 20
make check                                       # tests + no-LLM accuracy gate (needs the dataset)
```

## Team

The team coordinates through one pinned GitHub issue, the board. See [AGENTS.md](AGENTS.md).
