"""Publish a release to AWS: build, sign with KMS, upload to S3, create an IoT Job.

  python -m cloud.publish export-pubkey
  python -m cloud.publish publish --version 1.1.0 --security-version 3
  python -m cloud.publish verify-remote --version 1.1.0

Reads infra values from build/tf-outputs.json (created from `terraform output -json`).
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

from device import verify
from .release import build_release
from .signing import KmsSigner

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "build" / "tf-outputs.json"
PUBKEY = ROOT / "build" / "trusted_pubkey.pem"


def load_outputs(path=OUTPUTS) -> dict:
    raw = json.loads(Path(path).read_text())
    return {k: v["value"] for k, v in raw.items()}


def job_document(bucket: str, version: str) -> dict:
    base = f"https://{bucket}.s3.amazonaws.com/releases/{version}"
    ph = lambda name: f"${{aws:iot:s3-presigned-url:{base}/{name}}}"   # IoT fills in the URL
    return {"operation": "firmware-update", "version": version,
            "manifest_url": ph("manifest.json"), "signature_url": ph("manifest.sig"),
            "image_url": ph("fw.bin")}


def publish(out, version, security_version, kind="good", tamper=None, thing="device-001",
            group=None, timeout_min=None, region="us-east-1", job_id=None, expires_s=3600,
            s3=None, iot=None, signer=None) -> str:
    if not re.fullmatch(r"[0-9A-Za-z.\-]+", version):
        raise ValueError("bad version string")
    if s3 is None or iot is None:
        import boto3
        s3 = s3 or boto3.client("s3", region_name=region)
        iot = iot or boto3.client("iot", region_name=region)
    signer = signer or KmsSigner(out["kms_key_id"], region)

    artifacts = build_release(kind, version, security_version, signer, tamper=tamper)
    for name, data in artifacts.items():
        s3.put_object(Bucket=out["bucket_name"], Key=f"releases/{version}/{name}", Body=data)

    target = (iot.describe_thing_group(thingGroupName=group)["thingGroupArn"] if group
              else iot.describe_thing(thingName=thing)["thingArn"])
    job_id = job_id or f"ota-{version.replace('.', '-')}-{int(time.time())}"
    kwargs = dict(jobId=job_id, targets=[target],
                  document=json.dumps(job_document(out["bucket_name"], version)),
                  description=f"failsafe-ota {version} kind={kind} tamper={tamper}",
                  targetSelection="SNAPSHOT",
                  presignedUrlConfig={"roleArn": out["presign_role_arn"], "expiresInSec": expires_s})
    if timeout_min:
        kwargs["timeoutConfig"] = {"inProgressTimeoutInMinutes": timeout_min}
    iot.create_job(**kwargs)
    return job_id


def verify_remote(out, version, pubkey_path=PUBKEY, stored_sv=0, s3=None, region="us-east-1"):
    """Download a published release from S3 and verify it exactly as a device would."""
    if s3 is None:
        import boto3
        s3 = boto3.client("s3", region_name=region)
    get = lambda n: s3.get_object(Bucket=out["bucket_name"],
                                  Key=f"releases/{version}/{n}")["Body"].read()
    pub = verify.load_public_key(Path(pubkey_path).read_bytes())
    manifest = verify.verify_manifest(get("manifest.json"), get("manifest.sig"), pub, stored_sv)
    verify.verify_image(manifest, get("fw.bin"))
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cloud.publish")
    ap.add_argument("--outputs", default=str(OUTPUTS))
    ap.add_argument("--region", default="us-east-1")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("publish")
    p.add_argument("--version", required=True)
    p.add_argument("--security-version", type=int, required=True)
    p.add_argument("--kind", default="good")
    p.add_argument("--tamper", default=None)
    p.add_argument("--thing", default="device-001")
    p.add_argument("--group", default=None, help="target a thing group instead of one thing")
    p.add_argument("--timeout-min", type=int, default=None)
    sub.add_parser("export-pubkey")
    v = sub.add_parser("verify-remote")
    v.add_argument("--version", required=True)
    a = ap.parse_args(argv)

    out = load_outputs(a.outputs)
    if a.cmd == "export-pubkey":
        PUBKEY.write_bytes(KmsSigner(out["kms_key_id"], a.region).public_pem())
        print("wrote", PUBKEY)
    elif a.cmd == "publish":
        job_id = publish(out, a.version, a.security_version, a.kind, a.tamper, a.thing,
                         a.group, a.timeout_min, a.region)
        print("created job", job_id)
    else:
        m = verify_remote(out, a.version, region=a.region)
        print("verified OK:", m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
