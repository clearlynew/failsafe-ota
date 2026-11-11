"""Create (or reset) a simulated device directory: slot A runs good fw, state STABLE.

  python -m device.provision --root build/sim/device-001 --pubkey build/trusted_pubkey.pem
"""
import argparse
import shutil
from pathlib import Path

from . import slots
from .firmware import build_firmware


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--pubkey", required=True, help="trusted public key PEM (from KMS)")
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument("--security-version", type=int, default=2)
    a = ap.parse_args(argv)
    root = Path(a.root)
    root.mkdir(parents=True, exist_ok=True)
    for name in ("state.json", "state.json.tmp", "download.tmp"):   # reset previous run
        (root / name).unlink(missing_ok=True)
    for d in ("slot_a", "slot_b"):
        shutil.rmtree(root / d, ignore_errors=True)
    slots.provision(str(root), a.version, a.security_version,
                    build_firmware("good", a.version))
    shutil.copy(a.pubkey, root / "trusted_pubkey.pem")
    print(f"provisioned {root}: v{a.version}, security_version {a.security_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
