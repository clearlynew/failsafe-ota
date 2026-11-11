"""Health gate: alive + self-test + cloud heartbeat, all within a deadline."""
import logging
import threading
import time
from dataclasses import dataclass

from .transport import NetworkError

log = logging.getLogger("health")


@dataclass
class HealthConfig:
    deadline_s: float = 30.0
    min_alive_s: float = 5.0   # fw must stay up this long after start
    poll_s: float = 0.1


@dataclass
class HealthResult:
    ok: bool
    reason: str = None
    elapsed: float = 0.0


class _Monitor(threading.Thread):
    def __init__(self, proc):
        super().__init__(daemon=True)
        self.proc, self.seen = proc, set()

    def run(self):
        for line in self.proc.stdout:
            self.seen.add(line.strip())


def run_health_gate(proc, heartbeat, cfg: HealthConfig) -> HealthResult:
    mon = _Monitor(proc)
    mon.start()
    start, hb_ok, hb_failed = time.monotonic(), False, False
    while True:
        elapsed = time.monotonic() - start
        seen = set(mon.seen)
        if "SELFTEST_FAIL" in seen or proc.poll() is not None:
            return HealthResult(False, "HEALTH_CHECK_FAILED", elapsed)
        if {"SELFTEST_OK", "CLOUD_OK"} <= seen and not hb_ok:
            try:
                heartbeat()
                hb_ok = True
            except NetworkError:
                if not hb_failed:
                    log.warning("heartbeat failed, retrying within window")
                    hb_failed = True  # retry: a short blip must not roll back
        if hb_ok and elapsed >= cfg.min_alive_s:
            return HealthResult(True, None, elapsed)
        if elapsed >= cfg.deadline_s:
            if "SELFTEST_OK" not in seen:
                return HealthResult(False, "TRIAL_TIMEOUT", elapsed)   # silent / hung
            return HealthResult(False, "CLOUD_UNREACHABLE", elapsed)
        time.sleep(cfg.poll_s)
