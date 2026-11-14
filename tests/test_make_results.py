"""L1: the results generator turns evidence logs into the numbers, with nothing typed by hand."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("make_results", ROOT / "scripts" / "make_results.py")
mr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mr)

SCEN = """
- {id: S1, name: Good update, release: {}, expect: {job_status: SUCCEEDED, version: 1.1.0}}
- {id: S2a, name: Tampered, release: {}, expect: {job_status: FAILED, reason: HASH_MISMATCH, version: 1.0.0}}
"""
INV = "{'I2': True, 'I1': True, 'I3': True, 'I4': True, 'I5': True, 'I6': True, 'I7': True}"


def local_log(i, ok=True):
    return (f"{i}: x\nexpected: {{'job_status': 'FAILED'}}\nobserved: {{'job_status': 'FAILED', "
            f"'reason': 'HASH_MISMATCH', 'version': '1.0.0', 'security_version': 2}}\n"
            f"invariants: {INV}\nresult: {'PASS' if ok else 'FAIL'}\n--- device log ---\n")


def aws_log(i, ok=True):
    return (f"{i}: x (real AWS)\njob: e2e-{i}-1\nexpected: {{}}\nobserved: job={{'status': 'FAILED', "
            f"'details': {{'reason': 'HASH_MISMATCH'}}}} version=1.0.0 sv=2\ninvariants: {INV}\n"
            f"result: {'PASS' if ok else 'FAIL'}\n--- device log ---\n")


def s9_log(job, per_min, exposed, status, secs, avg):
    return (f"S9: bad release across 20 devices (real AWS)\njob: {job}\n"
            f"config: {per_min}/min, abort at 20.0% after 5 executed, fw kind=crash_now\n"
            f"job final status: {status} after {secs}s\ndevices exposed to the bad image: {exposed} / 20\n"
            f"failed executions: {exposed} reasons=['HEALTH_CHECK_FAILED'], avg start-to-rollback report: {avg}s\n"
            f"devices left on bad image: 0 []\nPASS: job aborted (CANCELED)\n")


def build(tmp_path):
    ev, aws = tmp_path / "evidence", tmp_path / "evidence" / "aws"
    aws.mkdir(parents=True)
    (tmp_path / "s.yaml").write_text(SCEN)
    (ev / "S1.log").write_text(local_log("S1")); (ev / "S2a.log").write_text(local_log("S2a", ok=False))
    for n in range(1, 11):
        (ev / f"S8-P{n}.log").write_text(local_log(f"S8-P{n}"))
    (aws / "S1.log").write_text(aws_log("S1")); (aws / "S2a.log").write_text(aws_log("S2a"))
    (aws / "S9.log").write_text(s9_log("s9-1", 4, 5, "CANCELED", 78, 5.7))
    (aws / "S9-4-per-min.log").write_text(s9_log("s9-1", 4, 5, "CANCELED", 78, 5.7))   # duplicate copy
    (aws / "S9-20-per-min.log").write_text(s9_log("s9-2", 20, 20, "COMPLETED", 60, 5.9))
    return ev, tmp_path / "s.yaml"


def test_headline_numbers_come_from_logs(tmp_path):
    ev, scen = build(tmp_path)
    md, head = mr.generate(ev, scen)
    assert "1 / 2 cases pass" in head and "2 / 2 scenarios pass" in head
    assert "10 / 10" in head
    assert "5 / 20 devices got the bad image; job CANCELED after 78s" in head
    assert "20 / 20 devices got the bad image; job COMPLETED after 60s" in head
    one_run = md.count("](evidence/aws/S9-4-per-min.log)") + md.count("](evidence/aws/S9.log)")
    assert one_run == 1 and md.count("](evidence/aws/S9-20-per-min.log)") == 1   # duplicate listed once
    assert head.index("5 / 20") < head.index("20 / 20")                          # slowest rollout first
    assert "5.7 s" in head
    assert "**FAIL**" in md                                               # failures are not hidden


def test_missing_logs_say_not_run(tmp_path):
    (tmp_path / "evidence").mkdir()
    (tmp_path / "s.yaml").write_text(SCEN)
    md, head = mr.generate(tmp_path / "evidence", tmp_path / "s.yaml")
    assert "0 / 0 cases pass" in head and "not run yet" in head and "not run" in md


def test_readme_block_replaced_in_place(tmp_path):
    r = tmp_path / "README.md"
    r.write_text("a\n<!-- HEADLINE:START -->\nold\n<!-- HEADLINE:END -->\nb\n")
    assert mr.update_readme(r, "NEW")
    assert r.read_text() == "a\n<!-- HEADLINE:START -->\nNEW\n<!-- HEADLINE:END -->\nb\n"
