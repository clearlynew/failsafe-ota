"""Release signers: LocalSigner (L2 tests) and KmsSigner (real AWS KMS, L3)."""
import base64
import hashlib

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


class KmsSigner:
    """Signs with an asymmetric KMS key (ECC_NIST_P256). The private key never leaves KMS."""

    def __init__(self, key_id: str, region: str = "us-east-1", client=None):
        if client is None:
            import boto3  # imported lazily so the local tests don't need boto3
            client = boto3.client("kms", region_name=region)
        self.kms, self.key_id = client, key_id

    def sign_manifest(self, manifest: dict) -> bytes:
        digest = hashlib.sha256(canonical_json(manifest)).digest()
        resp = self.kms.sign(KeyId=self.key_id, Message=digest, MessageType="DIGEST",
                             SigningAlgorithm="ECDSA_SHA_256")
        return base64.b64encode(resp["Signature"])      # KMS returns DER, same as LocalSigner

    def public_pem(self) -> bytes:
        der = self.kms.get_public_key(KeyId=self.key_id)["PublicKey"]
        return serialization.load_der_public_key(der).public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
