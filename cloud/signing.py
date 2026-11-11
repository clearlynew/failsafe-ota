"""Local ECDSA P-256 signer used by the L2 tests. A KMS signer replaces it in L3."""
import base64

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from device.verify import canonical_json


class LocalSigner:
    def __init__(self, private_key=None):
        self.key = private_key or ec.generate_private_key(ec.SECP256R1())

    def sign_manifest(self, manifest: dict) -> bytes:
        """base64(DER ECDSA) over SHA-256 of the canonical manifest JSON."""
        sig = self.key.sign(canonical_json(manifest), ec.ECDSA(hashes.SHA256()))
        return base64.b64encode(sig)

    def public_pem(self) -> bytes:
        return self.key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
