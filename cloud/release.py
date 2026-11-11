"""Build a release (fw.bin, manifest.json, manifest.sig), optionally tampered."""
import hashlib
import json

from device.firmware import build_firmware
from .signing import LocalSigner

TAMPERS = {None, "flip_image", "truncate_image", "wrong_key", "missing_sig",
           "garble_sig", "edit_sv", "edit_sha"}


def build_release(kind, version, security_version, signer, size=2048, tamper=None,
                  created="2026-11-12T10:00:00Z") -> dict:
    assert tamper in TAMPERS, tamper
    image = build_firmware(kind, version, size)
    manifest = {"name": "fw", "version": version, "security_version": security_version,
                "size": len(image), "sha256": hashlib.sha256(image).hexdigest(),
                "created": created}
    sig = (LocalSigner() if tamper == "wrong_key" else signer).sign_manifest(manifest)

    if tamper == "flip_image":
        image = image[:100] + bytes([image[100] ^ 0xFF]) + image[101:]
    elif tamper == "truncate_image":
        image = image[: len(image) // 2]
    elif tamper == "missing_sig":
        sig = b""
    elif tamper == "garble_sig":
        sig = b"AAAA" + sig[4:]
    elif tamper == "edit_sv":
        manifest["security_version"] += 1       # edited AFTER signing
    elif tamper == "edit_sha":
        manifest["sha256"] = "0" * 64
    return {"fw.bin": image, "manifest.sig": sig,
            "manifest.json": json.dumps(manifest, indent=2, sort_keys=True).encode()}


def publish_to_fake(jobs, job_id, version, artifacts, timeout_s=None):
    """Local stand-in for publish.py: upload blobs and create the job."""
    doc = {"operation": "firmware-update", "version": version}
    for field, name in (("manifest_url", "manifest.json"),
                        ("signature_url", "manifest.sig"), ("image_url", "fw.bin")):
        key = f"releases/{version}/{name}"
        jobs.put_blob(key, artifacts[name])
        doc[field] = jobs.url(key)
    jobs.create_job(job_id, doc, timeout_s=timeout_s)
