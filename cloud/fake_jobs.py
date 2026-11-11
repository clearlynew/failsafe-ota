"""File-backed fake of IoT Jobs + Shadow + S3, shareable across device subprocesses."""
import json
import os
import time

from device import faults
from device.transport import FetchError, JobRejected, NetworkError

TERMINAL = {"SUCCEEDED", "FAILED", "REJECTED", "TIMED_OUT", "CANCELED"}


class FakeJobs:
    def __init__(self, directory):
        self.dir = str(directory)
        for sub in ("blobs", "jobs", "shadow"):
            os.makedirs(os.path.join(self.dir, sub), exist_ok=True)

    # --- cloud-side helpers (publisher / harness) ---
    def url(self, key): return f"fake://{key}"

    def put_blob(self, key, data):
        path = os.path.join(self.dir, "blobs", key.replace("/", "__"))
        with open(path, "wb") as f:
            f.write(data)

    def _jpath(self, job_id): return os.path.join(self.dir, "jobs", f"{job_id}.json")

    def _load(self, job_id):
        with open(self._jpath(job_id)) as f:
            return json.load(f)

    def _save(self, job):
        with open(self._jpath(job["job_id"]), "w") as f:
            json.dump(job, f)

    def create_job(self, job_id, document, timeout_s=None):
        self._save({"job_id": job_id, "document": document, "status": "QUEUED",
                    "details": {}, "timeout_s": timeout_s, "started_at": None})

    def get_job(self, job_id): return self._load(job_id)

    def get_shadow(self, thing):
        try:
            with open(os.path.join(self.dir, "shadow", f"{thing}.json")) as f:
                return json.load(f)
        except FileNotFoundError:
            return None

    def sweep(self, now=None):
        """Apply timeoutConfig: IN_PROGRESS past its timeout becomes TIMED_OUT."""
        now = now or time.time()
        for name in sorted(os.listdir(os.path.join(self.dir, "jobs"))):
            job = self._load(name[:-5])
            if (job["status"] == "IN_PROGRESS" and job["timeout_s"]
                    and now - job["started_at"] > job["timeout_s"]):
                job["status"] = "TIMED_OUT"
                self._save(job)

    # --- device-facing transport ---
    def _net(self):
        if faults.net_blackholed():
            raise NetworkError("blackholed")

    def start_next(self, thing):
        self._net()
        for name in sorted(os.listdir(os.path.join(self.dir, "jobs"))):
            job = self._load(name[:-5])
            if job["status"] in ("QUEUED", "IN_PROGRESS"):
                if job["status"] == "QUEUED":
                    job["status"], job["started_at"] = "IN_PROGRESS", time.time()
                    self._save(job)
                return {"job_id": job["job_id"], "document": job["document"]}
        return None

    def update_job(self, thing, job_id, status, details):
        self._net()
        job = self._load(job_id)
        if job["status"] in TERMINAL:
            raise JobRejected(f"{job_id} already {job['status']}")
        job["status"], job["details"] = status, details
        self._save(job)

    def fetch(self, url, offset, length):
        self._net()
        path = os.path.join(self.dir, "blobs", url[len("fake://"):].replace("/", "__"))
        try:
            with open(path, "rb") as f:
                f.seek(offset)
                return f.read(length)
        except FileNotFoundError as e:
            raise FetchError(url) from e

    def heartbeat(self, thing): self._net()

    def update_shadow(self, thing, reported):
        self._net()
        with open(os.path.join(self.dir, "shadow", f"{thing}.json"), "w") as f:
            json.dump({"state": {"reported": reported}}, f)
