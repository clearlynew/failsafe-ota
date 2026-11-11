"""L1: atomic state writes and slot-write ordering under a simulated power cut."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from device import slots

ROOT = Path(__file__).resolve().parent.parent


def _run(code, fault):
    env = dict(os.environ, PYTHONPATH=str(ROOT), FAILSAFE_FAULT=fault)
    return subprocess.run([sys.executable, "-c", code], env=env, cwd=ROOT).returncode


def test_crash_before_rename_keeps_old_state(tmp_path):
    slots.provision(str(tmp_path), "1.0.0", 2, b"old")
    code = (f"from device import slots; r={str(tmp_path)!r}; s=slots.load_state(r); "
            "s['version']='9.9.9'; slots.atomic_write_state(r, s, tmp_point='flip_tmp_written')")
    assert _run(code, "flip_tmp_written") == 137
    assert (tmp_path / "state.json.tmp").exists()                     # torn write left behind
    assert slots.load_state(str(tmp_path), clean=False)["version"] == "1.0.0"
    slots.load_state(str(tmp_path))                                   # cleanup
    assert not (tmp_path / "state.json.tmp").exists()


def test_crash_mid_slot_write_leaves_active_slot_and_state_intact(tmp_path):
    slots.provision(str(tmp_path), "1.0.0", 2, b"old-image")
    code = f"from device import slots; slots.write_slot({str(tmp_path)!r}, 'B', b'x'*2048)"
    assert _run(code, "write_mid") == 137
    assert (tmp_path / "slot_a" / "fw.py").read_bytes() == b"old-image"
    assert slots.load_state(str(tmp_path))["active_slot"] == "A"
    assert os.path.getsize(tmp_path / "slot_b" / "fw.py") < 2048      # torn, but inactive


def test_invalid_state_rejected(tmp_path):
    with pytest.raises(slots.StateCorrupt):
        slots.validate_state({"active_slot": "C"})
