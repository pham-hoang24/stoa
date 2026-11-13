PY := .venv/bin/python -W ignore

.PHONY: test gate check
test: ## unit/seam tests
	$(PY) -m pytest -q

gate: ## no-LLM regression gate on ground truth (needs dataset); thresholds sit just under current scores
	$(PY) -m stoa.eval.run --lane swiss --min-acc 0.98
	$(PY) -m stoa.eval.run --lane ifc --source ifc_models --min-acc 0.96

check: test gate
