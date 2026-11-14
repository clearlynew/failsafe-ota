# 0002: Sign the manifest, not only the image

**Decision.** KMS signs the SHA-256 of the canonical manifest JSON. The manifest carries the image
hash, size, `version` and `security_version`.

**Why.** Signing only the image lets an attacker pair a valid image with altered metadata (for
example a lower security version). Signing the manifest binds all of it together.

**Cost.** Two artifacts to verify instead of one; canonical JSON must be stable (tested).

**Evidence.** S3a (wrong key), S3b (missing and corrupt signature), S3c (manifest edited after
signing, both `security_version` and `sha256`) all end `SIGNATURE_INVALID` locally and on AWS.
**Alternative not taken.** AWS Signer with IoT code-signing jobs.
