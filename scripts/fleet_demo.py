"""S9: a bad release across a 20-device fleet, stopped by slow rollout + an abort threshold.

    python scripts/fleet_demo.py                    # defaults: 4 devices/min, abort at 20%
    python scripts/fleet_demo.py --max-per-minute 20   # too fast: abort can't help

Needs 20 devices provisioned in AWS (see README) and build/tf-outputs.json.
Records: devices that received the bad image, devices left on it (must be 0), time to rollback.
"""
import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cloud import publish as pub          # noqa: E402
from device import slots                  # noqa: E402

GROUP = "fleet-a"
EXPOSED = {"SUCCEEDED", "FAILED", "TIMED_OUT", "REJECTED", "IN_PROGRESS"}   # got the new image


def summarize(executions: dict) -> dict:
    """executions: device -> {"status", "details", "seconds"} or None (never got one)."""
    exposed = [d for d, e in executions.items() if e and e["status"] in EXPOSED]
    failed = [e for e in executions.values() if e and e["status"] == "FAILED"]
    secs = [e["seconds"] for e in failed if e.get("seconds") is not None]
    return {"exposed": len(exposed), "total": len(executions),
            "failed": len(failed), "avg_rollback_s": round(sum(secs) / len(secs), 1) if secs else None,
            "reasons": sorted({e["details"].get("reason", "?") for e in failed})}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--devices", type=int, default=20)
    ap.add_argument("--version", default="2.0.0")
    ap.add_argument("--security-version", type=int, default=3)
    ap.add_argument("--kind", default="crash_now", help="the buggy firmware")
    ap.add_argument("--max-per-minute", type=int, default=4)
    ap.add_argument("--abort-threshold", type=float, default=20.0)
    ap.add_argument("--abort-min-executed", type=int, default=5)
    ap.add_argument("--max-seconds", type=int, default=420)
    ap.add_argument("--region", default="us-east-1")
    a = ap.parse_args()

    import boto3
    out = pub.load_outputs(ROOT / "build" / "tf-outputs.json")
    iot = boto3.client("iot", region_name=a.region)
    names = [f"device-{i:03d}" for i in range(1, a.devices + 1)]

    members = set()                                   # the API returns plain thing names, in pages
    for page in iot.get_paginator("list_things_in_thing_group").paginate(thingGroupName=GROUP):
        members.update(page["things"])
    missing = [n for n in names if n not in members]
    if missing:
        print(f"{len(missing)} devices are not in {GROUP} yet (e.g. {missing[:3]}): "
              "raise device_count in Terraform to 20 and apply first."); return 1
    for n in names:
        if not (ROOT / "build" / "devices" / n / "device.pem.crt").exists():
            print(f"missing certificate for {n}: run scripts/export_certs.sh"); return 1
    if iot.list_jobs(status="IN_PROGRESS").get("jobs"):
        print("another job is IN_PROGRESS and would be handed to the fleet; cancel it first."); return 1

    fleet = ROOT / "build" / "sim" / "fleet"
    (fleet / "logs").mkdir(parents=True, exist_ok=True)
    for n in names:                                   # fresh devices: 1.0.0, security_version 2
        subprocess.run([sys.executable, "-m", "device.provision", "--root", str(fleet / n),
                        "--pubkey", str(ROOT / "build" / "trusted_pubkey.pem")],
                       cwd=ROOT, check=True, capture_output=True)

    job_id = f"s9-{int(time.time())}"
    pub.publish(out, a.version, a.security_version, a.kind, group=GROUP, region=a.region,
                job_id=job_id, max_per_minute=a.max_per_minute,
                abort_threshold=a.abort_threshold, abort_min_executed=a.abort_min_executed)
    t0 = time.time()
    print(f"job {job_id}: {a.kind} fw to {a.devices} devices, {a.max_per_minute}/min, "
          f"abort at {a.abort_threshold}% after {a.abort_min_executed} executed")

    env = dict(os.environ, PYTHONPATH=str(ROOT))
    procs = []
    for n in names:
        log = open(fleet / "logs" / f"{n}.log", "w")
        procs.append(subprocess.Popen(
            [sys.executable, "-m", "device.updater", "--transport", "aws", "--thing", n,
             "--root", str(fleet / n), "--watch", str(a.max_seconds + 60), "--poll-interval", "3",
             "--health-deadline", "8", "--min-alive", "2", "--net-retry", "20"],
            cwd=ROOT, env=env, stdout=log, stderr=log))

    status = "IN_PROGRESS"
    try:
        while time.time() - t0 < a.max_seconds:
            job = iot.describe_job(jobId=job_id)["job"]
            status, d = job["status"], job.get("jobProcessDetails", {})
            print(f"  t={int(time.time() - t0):3d}s  {status:11s} queued={d.get('numberOfQueuedThings')} "
                  f"in_progress={d.get('numberOfInProgressThings')} failed={d.get('numberOfFailedThings')} "
                  f"canceled={d.get('numberOfCanceledThings')} succeeded={d.get('numberOfSucceededThings')}")
            if status in ("CANCELED", "COMPLETED"):
                break
            time.sleep(5)
        t_end = time.time() - t0
        time.sleep(25)                                # let in-flight devices finish their rollback
    finally:
        for p in procs:
            p.send_signal(signal.SIGTERM)
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()

    executions = {}
    for n in names:
        try:
            ex = iot.describe_job_execution(jobId=job_id, thingName=n)["execution"]
            executions[n] = {"status": ex["status"],
                             "details": ex.get("statusDetails", {}).get("detailsMap", {}),
                             "seconds": (ex["lastUpdatedAt"] - ex["startedAt"]).total_seconds()
                             if ex.get("startedAt") and ex["status"] == "FAILED" else None}
        except iot.exceptions.ResourceNotFoundException:
            executions[n] = None                      # rollout never reached this device
    s = summarize(executions)

    stuck = []                                        # invariant: nobody may stay on the bad image
    for n in names:
        st = slots.load_state(str(fleet / n))
        ok = (st["version"] == "1.0.0" and st["status"] == "STABLE" and
              slots.sha256_file(slots.slot_fw(str(fleet / n), st["active_slot"])) == st["active_image_sha256"])
        if not ok:
            stuck.append(n)

    checks = {"job aborted (CANCELED)": status == "CANCELED",
              "fewer than all devices exposed": s["exposed"] < s["total"],
              "no device left on the bad image": not stuck}
    lines = [f"S9: bad release across {a.devices} devices (real AWS)", f"job: {job_id}",
             f"config: {a.max_per_minute}/min, abort at {a.abort_threshold}% after "
             f"{a.abort_min_executed} executed, fw kind={a.kind}",
             f"job final status: {status} after {int(t_end)}s",
             f"devices exposed to the bad image: {s['exposed']} / {s['total']}",
             f"failed executions: {s['failed']} reasons={s['reasons']}, "
             f"avg start-to-rollback report: {s['avg_rollback_s']}s",
             f"devices left on bad image: {len(stuck)} {stuck}"]
    lines += [f"{'PASS' if v else 'FAIL'}: {k}" for k, v in checks.items()]
    text = "\n".join(lines)
    print("\n" + text)
    (ROOT / "docs" / "evidence" / "aws").mkdir(parents=True, exist_ok=True)
    (ROOT / "docs" / "evidence" / "aws" / "S9.log").write_text(text + "\n")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
