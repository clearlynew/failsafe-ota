"""Scenario harness: runs the device as a subprocess, injects faults, checks invariants I1-I7."""
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from cloud.fake_jobs import FakeJobs, TERMINAL
from cloud.release import build_release, publish_to_fake
from cloud.signing import LocalSigner
from device import slots
from device.firmware import build_firmware

ROOT = Path(__file__).resolve().parent.parent
THING, JOB_ID = "device-001", "job-1"


@dataclass
class Result:
    id: str
    name: str
    passed: bool = False
    failures: list = field(default_factory=list)
    observed: dict = field(default_factory=dict)
    invariants: dict = field(default_factory=dict)
    stderr: str = ""


def run_updater(root, jobs_dir, spec, fault=None, net=None):
    h = spec.get("health", {})
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    env.pop("FAILSAFE_FAULT", None); env.pop("FAILSAFE_NET_BLACKHOLE", None)
    if fault: env["FAILSAFE_FAULT"] = fault
    if net: env["FAILSAFE_NET_BLACKHOLE"] = net
    return subprocess.run(
        [sys.executable, "-m", "device.updater", "--root", str(root), "--jobs", str(jobs_dir),
         "--thing", THING, "--once", "--health-deadline", str(h.get("deadline_s", 3.0)),
         "--min-alive", str(h.get("min_alive_s", 1.0))],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)


def check_invariants(root, jobs, ctx) -> dict:
    inv = {}
    try:
        st = slots.load_state(root, clean=False)
    except slots.StateCorrupt:
        return {"I2": False}
    # I2: state.json parsed after every crash and at the end, and leftover .tmp files
    # were gone after every restart (tracked by run_scenario in ctx["i2"]).
    inv["I2"] = ctx["i2"]
    inv["I1"] = slots.sha256_file(slots.slot_fw(root, st["active_slot"])) == st["active_image_sha256"]
    inv["I3"] = st["active_image_sha256"] in ctx["trusted_hashes"]
    inv["I4"] = st["security_version"] >= ctx["initial_sv"]
    inv["I5"] = st["status"] == "STABLE"
    job = jobs.get_job(JOB_ID)
    exp = ctx["expect"]
    inv["I6"] = (job["status"] == exp["job_status"]
                 and (exp.get("reason") is None or job["details"].get("reason") == exp["reason"]))
    # was: sh = jobs.get_shadow(THING)
    sh = jobs.get_shadow(ctx.get("thing", THING))
    inv["I7"] = bool(sh) and sh["state"]["reported"]["version"] == st["version"]
    return inv


def run_scenario(spec, workdir) -> Result:
    res = Result(spec["id"], spec["name"])
    root, jdir = Path(workdir) / "device", Path(workdir) / "cloud"
    exp = spec["expect"]
    signer = LocalSigner()
    rel = spec["release"]
    dev = spec.get("device", {"version": "1.0.0", "security_version": 2})

    initial_fw = build_firmware("good", dev["version"])
    slots.provision(str(root), dev["version"], dev["security_version"], initial_fw)
    (root / "trusted_pubkey.pem").write_bytes(signer.public_pem())

    art = build_release(rel["kind"], rel["version"], rel["security_version"], signer,
                        tamper=rel.get("tamper"))
    clean = build_release(rel["kind"], rel["version"], rel["security_version"], signer)
    import hashlib
    ctx = {"initial_sv": dev["security_version"], "expect": exp, "trusted_hashes": {
        hashlib.sha256(initial_fw).hexdigest()} | (
        {hashlib.sha256(clean["fw.bin"]).hexdigest()}
        if rel.get("tamper") in (None, "flip_image", "truncate_image") else set())}

    jobs = FakeJobs(jdir)
    publish_to_fake(jobs, JOB_ID, rel["version"], art, timeout_s=spec.get("job_timeout_s"))
    inactive_before = slots.sha256_file(slots.slot_fw(str(root), "B"))

    fault = spec.get("fault", {})

    def parses():
        try:
            slots.load_state(str(root), clean=False)
            return True
        except slots.StateCorrupt:
            return False

    def no_leftovers():
        return not any((root / n).exists() for n in ("state.json.tmp", "download.tmp"))

    i2 = True
    runs = [run_updater(root, jdir, spec, fault.get("crash"), fault.get("net_blackhole"))]
    if fault.get("crash"):
        if runs[0].returncode != 137:
            res.failures.append(f"crash fault {fault['crash']} never fired (rc={runs[0].returncode})")
        i2 &= parses()                       # a torn .tmp must never corrupt state.json
        gone = spec.get("sequence") == "device_disappears"
        if gone:
            if jobs.get_job(JOB_ID)["status"] != "IN_PROGRESS":
                res.failures.append("job not IN_PROGRESS while device is gone")
            jobs.sweep(now=time.time() + spec["job_timeout_s"] + 1)
            if jobs.get_job(JOB_ID)["status"] != "TIMED_OUT":
                res.failures.append("job did not reach TIMED_OUT via timeoutConfig")
        for _ in range(3):                   # device comes back
            runs.append(run_updater(root, jdir, spec))
            i2 &= no_leftovers()             # .tmp files discarded on restart, never trusted
            if gone or jobs.get_job(JOB_ID)["status"] in TERMINAL:
                break
    runs.append(run_updater(root, jdir, spec))               # one more restart cycle (I5)
    i2 &= no_leftovers() and parses()
    ctx["i2"] = i2

    res.stderr = "\n".join(r.stderr for r in runs)
    st = slots.load_state(str(root), clean=False)
    # was: job = jobs.get_job(JOB_ID)
    job = jobs.get_job(ctx.get("job_id", JOB_ID))
    res.observed = {"job_status": job["status"], "reason": job["details"].get("reason"),
                    "version": st["version"], "security_version": st["security_version"]}
    res.invariants = check_invariants(str(root), jobs, ctx)

    for k, v in res.invariants.items():
        if not v: res.failures.append(f"invariant {k} failed")
    for k in ("version", "security_version"):
        if k in exp and exp[k] != res.observed[k]:
            res.failures.append(f"{k}: expected {exp[k]!r}, got {res.observed[k]!r}")
    if exp.get("inactive_untouched") and slots.sha256_file(slots.slot_fw(str(root), "B")) != inactive_before:
        res.failures.append("inactive slot was modified")
    if exp.get("stderr_contains") and exp["stderr_contains"] not in res.stderr:
        res.failures.append(f"log missing {exp['stderr_contains']!r}")
    res.passed = not res.failures
    return res
