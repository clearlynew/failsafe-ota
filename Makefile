PY ?= python3

setup:
	$(PY) -m venv .venv && .venv/bin/pip install -r requirements.txt

test-unit:
	$(PY) -m pytest -q tests/test_verify.py tests/test_state_atomicity.py

test-failures:
	$(PY) -m tests.run_scenarios

test-all:
	$(PY) -m pytest -q
	
tf-init:
	cd infra/terraform && terraform init

tf-apply:
	cd infra/terraform && terraform apply

tf-destroy:
	cd infra/terraform && terraform destroy
test-e2e:
	FAILSAFE_E2E=1 $(PY) -m pytest -q -v tests/test_e2e_aws.py

.PHONY: test-e2e

.PHONY: tf-init tf-apply tf-destroy

.PHONY: setup test-unit test-failures test-all
