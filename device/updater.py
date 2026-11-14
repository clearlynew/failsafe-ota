"""Jobs client + update state machine for one simulated device.

Run: python -m device.updater --root R --jobs J --thing device-001 --once
"""
import argparse
import logging
import os
import subprocess
import sys
import time

from . import faults, slots, verify
from .health import HealthConfig, run_health_gate
from .transport import FetchError, JobRejected, NetworkError

log = logging.getLogger("updater")
CHUNK = slots.CHUNK


class Updater:
    def __init__(self, root, thing, transport, pubkey_pem, health=None, net_retry_s=30.0):
        self.root, self.thing, self.t = str(root), thing, transport
        self.pub = verify.load_public_key(pubkey_pem)
        self.health = health or HealthConfig()
        self.net_retry_s = net_retry_s

    # ---------- network helpers ----------
    def _retry(self, fn):
        deadline, logged = time.monotonic() + self.net_retry_s, False
        while True:
            try:
                return fn()
            except NetworkError:
                if not logged:
                    log.warning("network error, retrying")
                    logged = True
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.2)

    def _report(self, job_id, status, details) -> bool:
        try:
            self._retry(lambda: self.t.update_job(self.thing, job_id, status, details))
            log.info("reported %s %s", status, details)
            return True
        except JobRejected as e:
            log.warning("job update rejected (tolerated): %s", e)
            return False

    def _sync_shadow(self):
        st = slots.load_state(self.root)
        if st["status"] == "TRIAL":
            return
        rep = {"version": st["version"], "slot": st["active_slot"],
               "status": st["status"], "security_version": st["security_version"]}
        try:
            self._retry(lambda: self.t.update_shadow(self.thing, rep))
        except NetworkError:
            log.warning("shadow update failed; will retry on next boot")

    def _fetch_bytes(self, url) -> bytes:
        out, off = b"", 0
        while True:
            chunk = self._retry(lambda: self.t.fetch(url, off, CHUNK))
            if not chunk:
                return out
            out, off = out + chunk, off + len(chunk)

    def _download_image(self, url) -> bytes:
        """Resumable download to download.tmp (P1/P2 crash points)."""
        path = os.path.join(self.root, "download.tmp")
        off = 0
        with open(path, "wb") as f:
            while True:
                chunk = self._retry(lambda: self.t.fetch(url, off, CHUNK))  # resumes at off
                if not chunk:
                    break
                f.write(chunk); f.flush(); os.fsync(f.fileno())
                off += len(chunk)
                faults.net_checkpoint("download_mid")
                faults.maybe_crash("download_mid")
        faults.maybe_crash("download_done")
        with open(path, "rb") as f:
            data = f.read()
        os.remove(path)
        return data

    # ---------- boot / recovery ----------
    def boot(self):
        st = slots.load_state(self.root)           # also discards .tmp files
        if st["status"] == "TRIAL":
            if st["trial_attempts_left"] > 0:
                st = dict(st, trial_attempts_left=st["trial_attempts_left"] - 1)
                slots.atomic_write_state(self.root, st)
                self._run_trial(st)
            else:
                log.warning("unconfirmed trial after restart: rolling back")
                self._rollback(st, "TRIAL_INTERRUPTED")
        self._flush_pending()
        self._sync_shadow()

    def _run_trial(self, st):
        fw = slots.slot_fw(self.root, st["active_slot"])
        proc = subprocess.Popen([sys.executable, fw], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True)
        try:
            faults.net_checkpoint("trial_start")
            faults.maybe_crash("trial_mid")
            res = run_health_gate(proc, lambda: self.t.heartbeat(self.thing), self.health)
        finally:
            proc.terminate()
            proc.wait()
        if not res.ok:
            log.warning("health gate failed: %s after %.1fs", res.reason, res.elapsed)
            return self._rollback(st, res.reason)
        faults.maybe_crash("health_passed")
        self._commit(st)
        faults.maybe_crash("post_commit")

    def _commit(self, st):
        pj = dict(st["pending_job"], result={"status": "SUCCEEDED"})
        slots.atomic_write_state(self.root, dict(
            st, status="STABLE", trial_attempts_left=0, previous=None, pending_job=pj,
            security_version=pj["new_security_version"]), tmp_point="commit_tmp_written")
        log.info("committed %s", st["version"])

    def _rollback(self, st, reason):
        prev = st["previous"]
        pj = dict(st["pending_job"], result={"status": "FAILED", "reason": reason})
        slots.atomic_write_state(self.root, dict(
            st, active_slot=prev["slot"], version=prev["version"],
            active_image_sha256=prev["sha256"], status="STABLE",
            trial_attempts_left=0, previous=None, pending_job=pj))
        log.warning("rolled back to %s (%s)", prev["version"], reason)

    def _flush_pending(self):
        st = slots.load_state(self.root)
        pj = st["pending_job"]
        if not pj or pj["result"] is None:
            return
        details = {"slot": pj["slot"], "from": pj["from"], "to": pj["to"]}
        if "reason" in pj["result"]:
            details["reason"] = pj["result"]["reason"]
        self._report(pj["job_id"], pj["result"]["status"], details)
        slots.atomic_write_state(self.root, dict(st, pending_job=None))

    # ---------- job handling ----------
    def process_job(self, job):
        st = slots.load_state(self.root)
        doc, job_id = job["document"], job["job_id"]
        if doc.get("operation") != "firmware-update":
            self._report(job_id, "REJECTED", {"reason": "UNSUPPORTED_OPERATION"})
            return
        if st["status"] == "STABLE" and st["version"] == doc["version"]:
            self._report(job_id, "SUCCEEDED", {"note": "already installed"})  # idempotent
            self._sync_shadow()
            return
        inactive = slots.other(st["active_slot"])
        details = {"slot": inactive, "from": st["version"], "to": doc["version"]}
        try:
            manifest = verify.verify_manifest(
                self._fetch_bytes(doc["manifest_url"]), self._fetch_bytes(doc["signature_url"]),
                self.pub, st["security_version"])
            if manifest["version"] != doc["version"]:
                raise verify.VerifyError("MANIFEST_INVALID", "version differs from job")
            image = self._download_image(doc["image_url"])
            verify.verify_image(manifest, image)
            slots.write_slot(self.root, inactive, image)
            if slots.sha256_file(slots.slot_fw(self.root, inactive)) != manifest["sha256"]:
                raise verify.VerifyError("HASH_MISMATCH", "read-back")
        except verify.VerifyError as e:
            log.error("rejected: %s", e)
            self._report(job_id, "FAILED", dict(details, reason=e.reason))
            self._sync_shadow()
            return
        except FetchError as e:
            log.error("download failed: %s", e)
            self._report(job_id, "FAILED", dict(details, reason="DOWNLOAD_FAILED"))
            return
        # single atomic commit point: from here the new slot is active, in TRIAL
        new = dict(st, active_slot=inactive, version=manifest["version"],
                   active_image_sha256=manifest["sha256"], status="TRIAL",
                   trial_attempts_left=1,
                   previous={"slot": st["active_slot"], "version": st["version"],
                             "sha256": st["active_image_sha256"]},
                   pending_job={"job_id": job_id, "from": st["version"],
                                "to": manifest["version"], "slot": inactive,
                                "new_security_version": manifest["security_version"],
                                "result": None})
        slots.atomic_write_state(self.root, new, tmp_point="flip_tmp_written")
        faults.maybe_crash("post_flip")
        self.boot()                                  # runs the trial, commits or rolls back

    def watch(self, seconds: float, interval: float = 3.0):
        """Keep polling for jobs (a staged rollout hands devices their job over time)."""
        self.boot()
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            job = self._retry(lambda: self.t.start_next(self.thing))
            if job:
                self.process_job(job)
            else:
                time.sleep(interval)
        self._sync_shadow()

    def run_once(self):
        self.boot()
        for _ in range(10):
            job = self._retry(lambda: self.t.start_next(self.thing))
            if job is None:
                break
            self.process_job(job)
        self._sync_shadow()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--transport", choices=("fake", "aws"), default="fake")
    ap.add_argument("--jobs", help="fake jobs directory (--transport fake)")
    ap.add_argument("--thing", default="device-001")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--watch", type=float, default=None, help="keep polling for this many seconds")
    ap.add_argument("--poll-interval", type=float, default=3.0)
    ap.add_argument("--health-deadline", type=float, default=30.0)
    ap.add_argument("--min-alive", type=float, default=5.0)
    ap.add_argument("--net-retry", type=float, default=30.0)
    ap.add_argument("--outputs", default="build/tf-outputs.json", help="aws: terraform outputs")
    ap.add_argument("--creds", default="build/devices", help="aws: dir holding <thing>/device.key etc.")
    ap.add_argument("--ca", default="build/AmazonRootCA1.pem")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(levelname)s %(name)s: %(message)s")
    if a.transport == "fake":
        from cloud.fake_jobs import FakeJobs
        transport = FakeJobs(a.jobs)
    else:
        import json
        from .aws_transport import AwsIotTransport
        endpoint = json.load(open(a.outputs))["iot_endpoint"]["value"]
        d = os.path.join(a.creds, a.thing)
        transport = AwsIotTransport(a.thing, endpoint, os.path.join(d, "device.pem.crt"),
                                    os.path.join(d, "device.key"), a.ca)
    with open(os.path.join(a.root, "trusted_pubkey.pem"), "rb") as f:
        pub = f.read()
    u = Updater(a.root, a.thing, transport, pub,
                HealthConfig(a.health_deadline, a.min_alive), a.net_retry)
    try:
        if a.watch:
            u.watch(a.watch, a.poll_interval)
        else:
            u.run_once()
    except NetworkError:
        log.error("cloud unreachable; exiting")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
