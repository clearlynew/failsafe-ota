#!/usr/bin/env bash
# After `terraform apply`: write each device's certificate next to its key, and fetch the
# Amazon root CA the device uses to verify AWS IoT.
# Usage: (cd infra/terraform && terraform output -json > ../../build/tf-outputs.json)
#        scripts/export_certs.sh
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
import json, pathlib
out = json.load(open("build/tf-outputs.json"))
for name, pem in out["device_certificates"]["value"].items():
    path = pathlib.Path("build/devices") / name / "device.pem.crt"
    path.write_text(pem)
    print("wrote", path)
PY

curl -fsSL -o build/AmazonRootCA1.pem https://www.amazontrust.com/repository/AmazonRootCA1.pem
echo "wrote build/AmazonRootCA1.pem"
