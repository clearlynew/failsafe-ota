"""L2: watch mode picks up a job that is published AFTER the device starts polling."""
import threading
import time

from cloud.fake_jobs import FakeJobs
from cloud.release import build_release, publish_to_fake
from cloud.signing import LocalSigner
from device import slots
from device.firmware import build_firmware
from device.health import HealthConfig
from device.updater import Updater


def test_watch_picks_up_late_job(tmp_path):
    signer, root = LocalSigner(), tmp_path / "dev"
    slots.provision(str(root), "1.0.0", 2, build_firmware("good", "1.0.0"))
    jobs = FakeJobs(tmp_path / "cloud")
    u = Updater(str(root), "device-001", jobs, signer.public_pem(), HealthConfig(3, 1, 0.1), 5)
    t = threading.Thread(target=u.watch, args=(6, 0.2))
    t.start()
    time.sleep(1.0)                                   # device is polling, nothing to do yet
    publish_to_fake(jobs, "job-late", "1.1.0", build_release("good", "1.1.0", 3, signer))
    t.join(timeout=30)
    assert jobs.get_job("job-late")["status"] == "SUCCEEDED"
    assert slots.load_state(str(root))["version"] == "1.1.0"
