"""A/B slot model + the single atomic commit point (state.json)."""
import hashlib
import json
import os

from . import faults

CHUNK = 512
STATE = "state.json"
REQUIRED = ("active_slot", "version", "security_version", "active_image_sha256",
            "status", "trial_attempts_left", "previous", "pending_job")


class StateCorrupt(Exception):
    pass


def other(slot: str) -> str:
    return "B" if slot == "A" else "A"


def slot_fw(root: str, slot: str) -> str:
    return os.path.join(root, f"slot_{slot.lower()}", "fw.py")


def sha256_file(path: str):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except FileNotFoundError:
        return None


def _fsync_dir(path: str) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def validate_state(s: dict) -> None:
    if not isinstance(s, dict) or any(k not in s for k in REQUIRED):
        raise StateCorrupt("missing keys")
    if s["active_slot"] not in ("A", "B") or s["status"] not in ("STABLE", "TRIAL"):
        raise StateCorrupt("bad slot/status")
    if not isinstance(s["security_version"], int) or not isinstance(s["trial_attempts_left"], int):
        raise StateCorrupt("bad ints")


def atomic_write_state(root: str, state: dict, tmp_point: str = None) -> None:
    """write tmp, fsync, [crash point], os.replace, fsync dir. The only commit point."""
    validate_state(state)
    final = os.path.join(root, STATE)
    tmp = final + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, sort_keys=True, indent=2)
        f.flush()
        os.fsync(f.fileno())
    if tmp_point:
        faults.maybe_crash(tmp_point)
    os.replace(tmp, final)
    _fsync_dir(root)


def load_state(root: str, clean: bool = True) -> dict:
    """Load state. With clean=True, leftover temp files are discarded, never trusted."""
    if clean:
        for name in (STATE + ".tmp", "download.tmp"):
            try:
                os.remove(os.path.join(root, name))
            except FileNotFoundError:
                pass
    try:
        with open(os.path.join(root, STATE)) as f:
            state = json.load(f)
    except (OSError, ValueError) as e:
        raise StateCorrupt(str(e)) from e
    validate_state(state)
    return state


def write_slot(root: str, slot: str, data: bytes) -> None:
    """Chunked write to the INACTIVE slot only, with crash points for P3/P4."""
    path = slot_fw(root, slot)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        for i in range(0, len(data), CHUNK):
            f.write(data[i:i + CHUNK])
            f.flush()
            os.fsync(f.fileno())
            if i + CHUNK < len(data):
                faults.maybe_crash("write_mid")
    _fsync_dir(os.path.dirname(path))
    faults.maybe_crash("write_done")


def provision(root: str, version: str, security_version: int, fw: bytes, slot: str = "A") -> None:
    os.makedirs(root, exist_ok=True)
    path = slot_fw(root, slot)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(fw)
    atomic_write_state(root, {
        "active_slot": slot, "version": version, "security_version": security_version,
        "active_image_sha256": hashlib.sha256(fw).hexdigest(), "status": "STABLE",
        "trial_attempts_left": 0, "previous": None, "pending_job": None})
