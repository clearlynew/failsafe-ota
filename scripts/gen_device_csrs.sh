#!/usr/bin/env bash
# Generate a private key + CSR per simulated device. Keys stay local (build/ is gitignored).
# Usage: scripts/gen_device_csrs.sh <count>
set -euo pipefail
cd "$(dirname "$0")/.."

count="${1:?usage: scripts/gen_device_csrs.sh <count>}"

for i in $(seq 1 "$count"); do
  name=$(printf "device-%03d" "$i")
  dir="build/devices/$name"
  mkdir -p "$dir"
  if [[ ! -f "$dir/device.key" ]]; then
    openssl genrsa -out "$dir/device.key" 2048 2>/dev/null
    chmod 600 "$dir/device.key"
  fi
  openssl req -new -key "$dir/device.key" -subj "/CN=$name" -out "$dir/device.csr"
  echo "ok $name"
done
