PY ?= python3

setup:
	$(PY) -m venv .venv && .venv/bin/pip install -r requirements.txt

test-unit:
	$(PY) -m pytest -q tests/test_verify.py tests/test_state_atomicity.py

test-failures:
	$(PY) -m tests.run_scenarios

test-all:
	$(PY) -m pytest -q

.PHONY: setup test-unit test-failures test-all
