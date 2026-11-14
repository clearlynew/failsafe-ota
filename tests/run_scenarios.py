"""Run the whole local matrix; write docs/evidence/*.log, results.json, the README matrix.

    python -m tests.run_scenarios      then      python scripts/make_results.py
"""
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from tests.harness import run_scenario

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    specs = yaml.safe_load((ROOT / "tests" / "scenarios.yaml").read_text())

    def one(spec):
        with tempfile.TemporaryDirectory() as d:
            return spec, run_scenario(spec, d)

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(one, specs))

    rows = ["| ID | Scenario | Expected | Observed | Invariants I1-I7 | Pass |", "|---|---|---|---|---|---|"]
    for spec, r in results:
        e, o = spec["expect"], r.observed
        exp = f"{e['job_status']}" + (f" `{e['reason']}`" if e.get("reason") else "") + f", v{e.get('version', '-')}"
        obs = f"{o['job_status']}" + (f" `{o['reason']}`" if o.get("reason") else "") + f", v{o['version']}"
        inv = "all" if r.invariants and all(r.invariants.values()) else \
            "FAIL: " + ",".join(k for k, v in r.invariants.items() if not v)
        rows.append(f"| {r.id} | {r.name} | {exp} | {obs} | {inv} | {'PASS' if r.passed else 'FAIL'} |")
    passed = sum(r.passed for _, r in results)
    md = f"# Failure results (L2, local fake Jobs transport)\n\n**Cases passed: {passed} / {len(results)}**\n\n" + "\n".join(rows) + "\n"
    (ROOT / "docs").mkdir(exist_ok=True)       # docs/RESULTS.md is written by scripts/make_results.py
    (ROOT / "results.json").write_text(json.dumps(
        [{"id": r.id, "passed": r.passed, "failures": r.failures, "observed": r.observed,
          "invariants": r.invariants} for _, r in results], indent=2))
    ev = ROOT / "docs" / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    for spec, r in results:
        (ev / f"{r.id}.log").write_text(
            f"{r.id}: {r.name}\nexpected: {spec['expect']}\nobserved: {r.observed}\n"
            f"invariants: {r.invariants}\nresult: {'PASS' if r.passed else 'FAIL'}\n"
            f"--- device log ---\n{r.stderr.strip()}\n")
    readme = ROOT / "README.md"
    text = readme.read_text()
    a, b = "<!-- MATRIX:START -->", "<!-- MATRIX:END -->"
    if a in text and b in text:
        block = f"{a}\n**{passed} / {len(results)} local failure cases pass**\n\n" + "\n".join(rows) + f"\n{b}"
        readme.write_text(text[:text.index(a)] + block + text[text.index(b) + len(b):])
    print(md)
    for _, r in results:
        if not r.passed:
            print(f"--- {r.id} FAILED: {r.failures}\n{r.stderr[-800:]}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
