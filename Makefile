PY := .venv/bin/python -W ignore

.PHONY: test gate check
test: ## unit/seam tests
	$(PY) -m pytest -q

gate: ## no-LLM regression gate on ground truth (needs dataset); fails if accuracy drops under the recorded baseline (src/stoa/eval/baseline.json)
	$(PY) -m stoa.eval.run --lane swiss --gate
	$(PY) -m stoa.eval.run --lane ifc --source ifc_models --gate

check: test gate
