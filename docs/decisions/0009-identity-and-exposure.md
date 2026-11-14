# 0009: Identity and exposure

**Decision.** Per-device X.509 certificates created from locally generated CSRs; an IoT policy that
uses the thing name so a device can only touch its own topics; S3 reachable only through expiring
presigned URLs issued by a role with a source-account condition; the signing key only in KMS.

**Why.** Device private keys never enter Terraform state or the repository (`build/` is ignored). A
compromised device cannot read another device's jobs or write to the release bucket.

**Limit.** Terraform state is local and holds resource ARNs; it must never be committed.

**Evidence.** Terraform in `infra/terraform/`; the simulated devices in every real-AWS scenario connect with
only these permissions (the release tooling uses the operator's own AWS credentials).
