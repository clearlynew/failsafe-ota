"""L2: the full scenario matrix against the fake Jobs transport."""
from pathlib import Path

import pytest
import yaml

from tests.harness import run_scenario

SCENARIOS = yaml.safe_load((Path(__file__).parent / "scenarios.yaml").read_text())


@pytest.mark.parametrize("spec", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
def test_scenario(spec, tmp_path):
    r = run_scenario(spec, tmp_path)
    assert r.passed, f"{r.failures}\nobserved={r.observed}\ninvariants={r.invariants}\n{r.stderr[-1500:]}"
