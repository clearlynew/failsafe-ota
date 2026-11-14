"""L3: the no-fault scenarios against real AWS (KMS, S3, IoT Jobs + Shadow).

Opt-in so a normal `pytest -q` never touches AWS:
    FAILSAFE_E2E=1 pytest -q tests/test_e2e_aws.py
Needs build/tf-outputs.json and build/trusted_pubkey.pem (see README steps).
"""
import hashlib
import json
import os
import subprocess
import sys
import time
import math
import pytest
import yaml

from cloud import publish as pub
from device import slots
from device.firmware import build_firmware
from tests.harness import ROOT, check_invariants

pytestmark = pytest.mark.skipif(os.environ.get("FAILSAFE_E2E") != "1",
                                reason="set FAILSAFE_E2E=1 to run against real AWS")

THING = "device-001"
TERMINAL = {"SUCCEEDED", "FAILED", "REJECTED", "TIMED_OUT", "CANCELED", "REMOVED"}
EVIDENCE = ROOT / "docs" / "evidence" / "aws"
# No-fault scenarios, plus the fault ones worth proving through real Jobs: network drops
# (S6b-d), the device vanishing until AWS times the job out (S7b/c), and power cuts P4/P7/P10.
AWS_FAULT_IDS = {"S6b", "S6c", "S6d", "S7bc", "S8-P4", "S8-P7", "S8-P10"}
SPECS = [s for s in yaml.safe_load((ROOT / "tests" / "scenarios.yaml").read_text())
         if ("fault" not in s and "job_timeout_s" not in s) or s["id"] in AWS_FAULT_IDS]
         
class AwsView:
    """Looks like FakeJobs to harness.check_invariants, but reads real AWS state."""
    def __init__(self, iot, iot_data, job_id):
        self.iot, self.iot_data, self.job_id = iot, iot_data, job_id

    def get_job(self, _id=None):
        ex = self.iot.describe_job_execution(jobId=self.job_id, thingName=THING)["execution"]
        return {"status": ex["status"], "details": ex.get("statusDetails", {}).get("detailsMap", {})}

    def get_shadow(self, _thing=None):
        return json.loads(self.iot_data.get_thing_shadow(thingName=THING)["payload"].read())


@pytest.fixture(scope="module")
def aws():
    import boto3
    outputs, pubkey = ROOT / "build" / "tf-outputs.json", ROOT / "build" / "trusted_pubkey.pem"
    if not outputs.exists() or not pubkey.exists():
        pytest.fail("missing build/tf-outputs.json or build/trusted_pubkey.pem; "
                    "run `terraform output -json` and `python -m cloud.publish export-pubkey`")
    out, region = pub.load_outputs(outputs), "us-east-1"
    iot = boto3.client("iot", region_name=region)
    iot_data = boto3.client("iot-data", region_name=region,
                            endpoint_url=f"https://{out['iot_endpoint']}")
    stale = []
    for status in ("QUEUED", "IN_PROGRESS"):
        stale += [e["jobId"] for e in iot.list_job_executions_for_thing(
            thingName=THING, status=status).get("executionSummaries", [])]
    if stale:
        pytest.fail(f"{THING} has unfinished jobs that would be picked up instead: {stale}. "
                    "Cancel them (aws iot cancel-job --force) and re-run.")
    return {"out": out, "iot": iot, "iot_data": iot_data, "region": region, "pubkey": pubkey}


def _wait(fn, seconds, what):
    end = time.time() + seconds
    while True:
        try:
            result = fn()
            if result:
                return result
        except Exception:
            if time.time() > end:
                raise
        if time.time() > end:
            raise AssertionError(f"timed out waiting for {what}")
        time.sleep(0.5)


@pytest.mark.parametrize("spec", SPECS, ids=[s["id"] for s in SPECS])
def test_scenario_on_aws(spec, aws, tmp_path):
    rel, exp, fault = spec["release"], spec["expect"], spec.get("fault", {})
    dev = spec.get("device", {"version": "1.0.0", "security_version": 2})
    root, env = tmp_path / "device", dict(os.environ, PYTHONPATH=str(ROOT))
    subprocess.run([sys.executable, "-m", "device.provision", "--root", str(root),
                    "--pubkey", str(aws["pubkey"]), "--version", dev["version"],
                    "--security-version", str(dev["security_version"])],
                   cwd=ROOT, env=env, check=True, capture_output=True)
    initial_fw = build_firmware("good", dev["version"])
    inactive_before = slots.sha256_file(slots.slot_fw(str(root), "B"))

    timeout_min = math.ceil(spec["job_timeout_s"] / 60) if "job_timeout_s" in spec else None
    job_id = pub.publish(aws["out"], rel["version"], rel["security_version"], rel["kind"],
                         rel.get("tamper"), thing=THING, region=aws["region"],
                         timeout_min=timeout_min,
                         job_id=f"e2e-{spec['id']}-{int(time.time())}")
    view = AwsView(aws["iot"], aws["iot_data"], job_id)
    h = spec.get("health", {})

    def run_device(fault_env=None):
        return subprocess.run(
            [sys.executable, "-m", "device.updater", "--transport", "aws", "--thing", THING,
             "--root", str(root), "--once", "--health-deadline", str(h.get("deadline_s", 8)),
             "--min-alive", str(h.get("min_alive_s", 2)), "--net-retry", "20"],
            cwd=ROOT, env=dict(env, **(fault_env or {})), capture_output=True, text=True,
            timeout=180)

    try:
        # job creation is asynchronous: wait until the device's execution exists
        _wait(lambda: aws["iot"].describe_job_execution(jobId=job_id, thingName=THING),
              30, "job execution to appear")
        fault_env = {}
        if fault.get("crash"):
            fault_env["FAILSAFE_FAULT"] = fault["crash"]
        if fault.get("net_blackhole"):
            fault_env["FAILSAFE_NET_BLACKHOLE"] = fault["net_blackhole"]
        procs, failures = [run_device(fault_env)], []
        if fault.get("crash"):
            if procs[0].returncode != 137:
                failures.append(f"crash fault {fault['crash']} never fired (rc={procs[0].returncode})")
            if spec.get("sequence") == "device_disappears":   # S7b: device stays dead
                _wait(lambda: view.get_job()["status"] == "TIMED_OUT", 400,
                      "AWS to time the job out (timeoutConfig)")
            for _ in range(3):                                 # device comes back
                procs.append(run_device())
                if view.get_job()["status"] in TERMINAL:
                    break
        stderr = "\n".join(p.stderr for p in procs)

        st = slots.load_state(str(root), clean=False)
        try:   # shadow updates are asynchronous: wait until it reflects the device
            _wait(lambda: view.get_shadow()["state"]["reported"].get("version") == st["version"],
                  10, "shadow to match device")
        except Exception:
            pass
        sha = lambda b: hashlib.sha256(b).hexdigest()
        trusted = {sha(initial_fw)}
        if rel.get("tamper") in (None, "flip_image", "truncate_image"):
            trusted.add(sha(build_firmware(rel["kind"], rel["version"])))
        leftovers = any((root / n).exists() for n in ("state.json.tmp", "download.tmp"))
        ctx = {"initial_sv": dev["security_version"], "expect": exp, "i2": not leftovers,
               "trusted_hashes": trusted, "job_id": job_id, "thing": THING}
        inv = check_invariants(str(root), view, ctx)
        job = view.get_job()

        failures += [f"invariant {k} failed" for k, v in inv.items() if not v]
        for k in ("version", "security_version"):
            if k in exp and exp[k] != st[k]:
                failures.append(f"{k}: expected {exp[k]!r}, got {st[k]!r}")
        if exp.get("inactive_untouched") and \
                slots.sha256_file(slots.slot_fw(str(root), "B")) != inactive_before:
            failures.append("inactive slot was modified")
        if exp.get("stderr_contains") and exp["stderr_contains"] not in stderr:
            failures.append(f"log missing {exp['stderr_contains']!r}")

        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (EVIDENCE / f"{spec['id']}.log").write_text(
            f"{spec['id']}: {spec['name']} (real AWS)\njob: {job_id}\nexpected: {exp}\n"
            f"observed: job={job} version={st['version']} sv={st['security_version']}\n"
            f"invariants: {inv}\nresult: {'PASS' if not failures else 'FAIL'}\n"
            f"--- device log ---\n{stderr.strip()}\n")
        assert not failures, f"{failures}\nobserved job={job}\n{stderr[-1500:]}"
    finally:  # never leave our own job active for the next scenario
        try:
            if view.get_job()["status"] not in TERMINAL:
                aws["iot"].cancel_job(jobId=job_id, force=True)
        except Exception:
            pass
