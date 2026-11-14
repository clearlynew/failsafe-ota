"""Generate docs/RESULTS.md and the README headline block from the evidence logs.

    python scripts/make_results.py

Every number comes from docs/evidence/*.log (local, fake cloud) and docs/evidence/aws/*.log
(real AWS). Nothing is typed by hand, and a missing log shows as "not run".
"""
import argparse
import ast
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
HEAD_START, HEAD_END = "<!-- HEADLINE:START -->", "<!-- HEADLINE:END -->"


def _field(text, key):
    m = re.search(rf"^{key}: (\{{.*\}})$", text, re.M)
    return ast.literal_eval(m.group(1)) if m else {}


def parse_scenario_log(path: Path) -> dict:
    text = path.read_text()
    result = re.search(r"^result: (PASS|FAIL)", text, re.M)
    obs = _field(text, "observed")
    if not obs:                                   # AWS format: observed: job={...} version=X sv=Y
        m = re.search(r"^observed: job=(\{.*\}) version=(\S+) sv=(\S+)", text, re.M)
        if m:
            job = ast.literal_eval(m.group(1))
            obs = {"job_status": job["status"], "reason": job["details"].get("reason"),
                   "version": m.group(2), "security_version": m.group(3)}
    return {"passed": bool(result) and result.group(1) == "PASS",
            "invariants": _field(text, "invariants"), "observed": obs, "file": path.name}


def parse_s9_log(path: Path) -> dict:
    t = path.read_text()
    def g(pat, cast=str):
        m = re.search(pat, t, re.M)
        return cast(m.group(1)) if m else None
    return {
        "job": g(r"^job: (\S+)"),
        "config": g(r"^config: (.*)$"),
        "status": g(r"^job final status: (\w+)"),
        "seconds": g(r"^job final status: \w+ after (\d+)s", int),
        "exposed": g(r"exposed to the bad image: (\d+) /", int),
        "total": g(r"exposed to the bad image: \d+ / (\d+)", int),
        "avg_rollback": g(r"avg start-to-rollback report: ([\d.]+)s", float),
        "stuck": g(r"devices left on bad image: (\d+)", int),
        "checks": re.findall(r"^(PASS|FAIL): (.*)$", t, re.M),
        "file": path.name}


def load_logs(evidence: Path):
    local = {p.stem: parse_scenario_log(p) for p in evidence.glob("*.log") if not p.name.startswith("S9")}
    aws_dir = evidence / "aws"
    aws = {p.stem: parse_scenario_log(p) for p in aws_dir.glob("*.log") if not p.name.startswith("S9")} \
        if aws_dir.exists() else {}
    s9, seen = [], set()
    for p in sorted(aws_dir.glob("S9*.log")) if aws_dir.exists() else []:
        r = parse_s9_log(p)
        if r["job"] not in seen:                  # S9.log is usually a copy of one named run
            seen.add(r["job"]); s9.append(r)
    rate = lambda r: int(re.match(r"(\d+)/min", r["config"] or "").group(1)) if r["config"] else 0
    s9.sort(key=rate)                             # slowest (protected) rollout first
    return local, aws, s9


def _cell(r, folder):
    if r is None:
        return "not run"
    return f"{'PASS' if r['passed'] else '**FAIL**'} ([log]({folder}{r['file']}))"


def _exp(e):
    s = e["job_status"] + (f" `{e['reason']}`" if e.get("reason") else "")
    return s + (f", v{e['version']}" if e.get("version") else "")


def generate(evidence: Path, scenarios_yaml: Path):
    specs = yaml.safe_load(scenarios_yaml.read_text())
    local, aws, s9 = load_logs(evidence)
    ids = [s["id"] for s in specs]

    rows = ["| ID | Scenario | Expected | Local (simulated cloud) | Real AWS |", "|---|---|---|---|---|"]
    for s in specs:
        rows.append(f"| {s['id']} | {s['name']} | {_exp(s['expect'])} | "
                    f"{_cell(local.get(s['id']), 'evidence/')} | {_cell(aws.get(s['id']), 'evidence/aws/')} |")

    l2_pass = sum(local[i]["passed"] for i in ids if i in local)
    l2_run = sum(i in local for i in ids)
    l3_pass = sum(aws[i]["passed"] for i in ids if i in aws)
    l3_run = sum(i in aws for i in ids)
    p_ids = [f"S8-P{n}" for n in range(1, 11)]
    p_ok = sum(1 for i in p_ids if i in local and local[i]["passed"]
               and local[i]["invariants"].get("I1") and local[i]["invariants"].get("I5"))

    head = [f"- **Local failure matrix (simulated cloud):** {l2_pass} / {l2_run} cases pass"
            + ("" if l2_run == len(ids) else f" ({len(ids) - l2_run} not run)"),
            f"- **Real AWS (KMS, S3, IoT Jobs, Shadow):** "
            + (f"{l3_pass} / {l3_run} scenarios pass" if l3_run else "not run yet"),
            f"- **Power-cut points that leave no unrunnable device (S8, P1 to P10):** {p_ok} / 10"]
    if s9:
        for r in s9:
            head.append(f"- **Bad fleet release ({r['config'].split(', fw')[0]}):** "
                        f"{r['exposed']} / {r['total']} devices got the bad image; job {r['status']} "
                        f"after {r['seconds']}s; devices left on it: {r['stuck']}")
        base = s9[0]
        if base["avg_rollback"] is not None:
            head.append(f"- **Bad install to rollback reported (average, slowest-rollout run):** "
                        f"{base['avg_rollback']} s")
    else:
        head.append("- **Bad fleet release (S9):** not run yet")
    headline = "\n".join(head)

    s9_rows = ["| Run | Config | Exposed | Final job status | Left on bad image | Checks |", "|---|---|---|---|---|---|"]
    for r in s9:
        checks = "; ".join(f"{'PASS' if v == 'PASS' else '**FAIL**'} {k}" for v, k in r["checks"])
        s9_rows.append(f"| [{r['file']}](evidence/aws/{r['file']}) | {r['config']} | {r['exposed']} / {r['total']} | "
                       f"{r['status']} after {r['seconds']}s | {r['stuck']} | {checks} |")

    md = ["# Results", "", "Generated by `python scripts/make_results.py` from the evidence logs. "
          "Do not edit by hand.", "", "## Headline numbers", "", headline, "",
          "## Failure matrix", "", "\n".join(rows), ""]
    if s9:
        md += ["## S9: bad release across the fleet", "", "\n".join(s9_rows), "",
               "A run is allowed to fail a check: the fast-rollout run exists to show that a rollout faster "
               "than the abort can react defeats the abort.", ""]
    return "\n".join(md), headline


def update_readme(readme: Path, headline: str):
    if not readme.exists():
        return False
    text = readme.read_text()
    if HEAD_START in text and HEAD_END in text:
        new = text[:text.index(HEAD_START)] + f"{HEAD_START}\n{headline}\n{HEAD_END}" + \
            text[text.index(HEAD_END) + len(HEAD_END):]
        readme.write_text(new)
        return True
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", default=str(ROOT / "docs" / "evidence"))
    ap.add_argument("--scenarios", default=str(ROOT / "tests" / "scenarios.yaml"))
    ap.add_argument("--out", default=str(ROOT / "docs" / "RESULTS.md"))
    ap.add_argument("--readme", default=str(ROOT / "README.md"))
    a = ap.parse_args(argv)
    md, headline = generate(Path(a.evidence), Path(a.scenarios))
    Path(a.out).write_text(md)
    updated = update_readme(Path(a.readme), headline)
    print(headline)
    print(f"\nwrote {a.out}" + (" and updated the README headline" if updated else
                                " (README has no HEADLINE markers)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
