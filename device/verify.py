"""Release verification: signature, schema, downgrade floor, size, hash (in that order)."""
import base64
import hashlib
import json

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

# Reason codes: SIGNATURE_INVALID, MANIFEST_INVALID, DOWNGRADE_REJECTED,
#               SIZE_MISMATCH, HASH_MISMATCH
FIELDS = {"name": str, "version": str, "security_version": int,
          "size": int, "sha256": str, "created": str}


class VerifyError(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode()


def load_public_key(pem: bytes):
    return serialization.load_pem_public_key(pem)


def verify_manifest(manifest_bytes: bytes, sig_b64: bytes, public_key,
                    stored_security_version: int) -> dict:
    """Return the manifest only if it is signed, well-formed and not a downgrade."""
    try:
        manifest = json.loads(manifest_bytes)
        sig = base64.b64decode(sig_b64, validate=True)
        public_key.verify(sig, canonical_json(manifest), ec.ECDSA(hashes.SHA256()))
    except Exception as e:  # any failure means the manifest is not trusted
        raise VerifyError("SIGNATURE_INVALID", type(e).__name__) from e

    for key, typ in FIELDS.items():
        v = manifest.get(key) if isinstance(manifest, dict) else None
        if not isinstance(v, typ) or isinstance(v, bool):
            raise VerifyError("MANIFEST_INVALID", f"bad field {key}")
    if manifest["security_version"] < stored_security_version:
        raise VerifyError("DOWNGRADE_REJECTED",
                          f"{manifest['security_version']} < {stored_security_version}")
    return manifest


def verify_image(manifest: dict, image: bytes) -> None:
    if len(image) != manifest["size"]:
        raise VerifyError("SIZE_MISMATCH", f"{len(image)} != {manifest['size']}")
    if hashlib.sha256(image).hexdigest() != manifest["sha256"]:
        raise VerifyError("HASH_MISMATCH")
