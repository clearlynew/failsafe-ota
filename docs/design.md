# failsafe-ota: A Failure-First OTA Update Protocol on AWS IoT

> **Problem statement:** Deliver signed firmware updates from AWS to edge devices so that a tampered, faulty, interrupted, or abandoned update can never leave a device without a verified, runnable image, and a bad release stops itself before it reaches the whole fleet.

**What this project is:** an implementation of the *update protocol, failure handling, and AWS integration* for a fail-safe OTA pipeline, tested against a deliberate catalog of failures.
**What it is not:** a bootloader. Devices are **simulated** by a Python A/B slot model (see [section 7](#7-what-is-simulated-and-what-is-real)).

**Stack:** Python (`awsiotsdk`, `boto3`, `cryptography`, `pytest`), AWS IoT Core, IoT Jobs, Device Shadow, S3, KMS (asymmetric signing), Terraform.

**Status:** built and tested. 28 local scenarios, 21 scenarios against real AWS, and the 20-device fleet runs all pass. Numbers are generated into [RESULTS.md](RESULTS.md) (this is a design document, so it does not repeat them). Section 15 lists where the build differs from the original plan.

---

## 1. Goals and non-goals

**Goals**
- Reject any release that is unsigned, tampered, or older than the device's security floor.
- In the simulator, never leave a device without a verified runnable slot, no matter where an update is interrupted.
- Roll back automatically when new firmware is unhealthy, loses cloud connectivity, or goes silent.
- Limit the blast radius of a bad release across a fleet.
- **Prove each claim with a repeatable, automated failure test** (section 2).
- Provision all AWS infrastructure with Terraform (section 6).

**Non-goals**
- A real bootloader, real flash partitions, secure boot, or a hardware root of trust.
- Delta updates, encrypted images, a web UI.

---

## 2. Failure testing is the centrepiece

The success path (S1) is one row in a table of 28 local cases, 21 of which also run against real AWS. The README leads with the failure results matrix, not a happy-path demo.

### 2.1 Required demonstrations

| Required demonstration | Scenarios | Proof artifact |
|---|---|---|
| Tampered firmware rejected | S2a, S2b | `HASH_MISMATCH` / `SIZE_MISMATCH`; inactive slot unchanged; job FAILED |
| Invalid signatures rejected | S3a, S3b, S3c | `SIGNATURE_INVALID`; manifest never trusted |
| Downgrade attempts rejected | S4a (S4b shows the allowed case) | `DOWNGRADE_REJECTED`; `security_version` unchanged |
| Firmware crashes and rolls back | S5a, S5b | job FAILED `HEALTH_CHECK_FAILED`; old slot active again; shadow shows old version |
| Device loses cloud connectivity | S6a, S6b, S6c, S6d | rollback `CLOUD_UNREACHABLE`; resumed download; tolerated blip |
| Device disappears during an update | S7a, S7b, S7c | rollback on deadline; job `TIMED_OUT`; clean recovery on return |
| Power interruption at different stages | S8 P1 to P10 | per-point after-restart table (2.6) |
| Bad release across a fleet *(bonus)* | S9 | abort fires; devices exposed `n / 20` |

### 2.2 Test pyramid

```
            +--------------------------------+
            | L3: end-to-end on AWS          |  real IoT Jobs, KMS, S3, Terraform infra
            |     21 cases, minutes          |  (manual / pre-release)
            +--------------------------------+
        +--------------------------------------+
        | L2: scenario matrix, local           |  fake Jobs transport + fault injection
        |     28 cases, ~35 secs               |  runs in CI on every push
        +--------------------------------------+
    +------------------------------------------------+
    | L1: unit tests                                 |  verify.py, canonical manifest,
    |     fast, no network                           |  atomic state writes
    +------------------------------------------------+
```

- **L2 is where the full matrix lives.** Every scenario and all 10 crash points run against a file-backed fake Jobs transport, so the whole matrix finishes in well under a minute and runs in CI.
- **L3 proves the AWS integration** (opt-in: `FAILSAFE_E2E=1`). It runs every scenario that needs no injected fault, plus S6b to S6d, S7b/S7c and the S8 subset P4, P7, P10 (21 in all), and S9 separately as `scripts/fleet_demo.py`. Jobs, signing, S3 and Shadow are real; the S6 network faults are injected inside the device's own transport, not as real packet loss.

### 2.3 Fault injection

Faults are injected deterministically at named points instead of with timing races.

```python
# device/faults.py   (test-only hooks; inert unless an environment variable is set)
maybe_crash("write_mid")            # FAILSAFE_FAULT=write_mid: os._exit(137), a simulated power cut
net_checkpoint("download_mid")      # FAILSAFE_NET_BLACKHOLE=download_mid:1.5: drop all network I/O for 1.5 s
```

- `maybe_crash(point)` calls `os._exit`, which skips `finally` blocks and Python-level buffers, approximating an abrupt power cut at *process* level.
- **Known limitation:** killing a process does not discard the OS page cache the way a real power loss can discard un-fsynced data. A process kill therefore proves the *ordering* of writes and the commit point, but not durability. Stretch goal: a test-only file layer that drops writes not followed by `fsync`.
- Fault hooks are never part of a "production" device path; they only activate through those environment variables.

### 2.4 Invariants (checked after every scenario)

Every scenario, whatever its expected outcome, must also satisfy these. A scenario fails if any invariant fails.

| # | Invariant |
|---|---|
| I1 | The active slot's image hash equals `active_image_sha256` in state (the device could run it). |
| I2 | `state.json` parses after every crash and at the end of the run, and leftover `.tmp` files are gone after the restart (never trusted). |
| I3 | The active image is one the trusted key signed (or the device's initial image); a tampered or unsigned image is never active. |
| I4 | `security_version` never decreases. |
| I5 | After one restart cycle the device is not stuck in `TRIAL`. |
| I6 | The job execution reaches the expected terminal status and reason (or is retried). |
| I7 | The shadow's reported version equals the version actually running once things settle. |

### 2.5 Scenario catalog

Expected outcomes are declared in `tests/scenarios.yaml`. `tests/run_scenarios.py` (local) and `tests/test_e2e_aws.py` (AWS) execute them and write evidence logs; `scripts/make_results.py` generates `docs/RESULTS.md` from those logs.

| ID | Scenario | How it is injected | Expected device result | Expected job result |
|---|---|---|---|---|
| S1 | Good update (baseline) | v1.1.0, healthy | Committed, new version | SUCCEEDED |
| S2a | Tampered image | Flip bytes in `fw.bin` after signing | Never written; old slot active | FAILED `HASH_MISMATCH` |
| S2b | Truncated image | Cut `fw.bin` short | Rejected before install | FAILED `SIZE_MISMATCH` |
| S3a | Wrong-key signature | Sign manifest with another key | Manifest not trusted | FAILED `SIGNATURE_INVALID` |
| S3b | Missing or corrupt signature file (`S3b-missing`, `S3b-garbled`) | Delete or garble `manifest.sig` | Manifest not trusted | FAILED `SIGNATURE_INVALID` |
| S3c | Manifest edited after signing (`S3c-sv`, `S3c-sha`) | Change `security_version` or `sha256` in the manifest | Signature check fails | FAILED `SIGNATURE_INVALID` |
| S4a | Downgrade attack | Validly signed release with lower `security_version` | Rejected | FAILED `DOWNGRADE_REJECTED` |
| S4b | Allowed rollback of `version` | Older `version`, same `security_version` | Installed (policy allows it) | SUCCEEDED |
| S5a | Firmware crashes at start | New fw exits immediately | Rolled back | FAILED `HEALTH_CHECK_FAILED` |
| S5b | Firmware crashes mid-trial | New fw reports healthy, then exits before the minimum-alive window ends | Rolled back | FAILED `HEALTH_CHECK_FAILED` |
| S6a | New fw cannot reach cloud | Fw skips IoT connection | Rolled back | FAILED `CLOUD_UNREACHABLE` |
| S6b | Network drops mid-download | `net_fault` during download | Resumes or retries; no corrupt slot | SUCCEEDED after retry |
| S6c | Short outage during trial | Blackhole shorter than trial deadline | Health gate retries; commits | SUCCEEDED |
| S6d | Long outage during trial | Blackhole longer than deadline | Rolled back (documented tradeoff) | FAILED `CLOUD_UNREACHABLE` |
| S7a | Firmware hangs, never confirms | Fw alive but silent | Rolled back at deadline | FAILED `TRIAL_TIMEOUT` |
| S7b | Device disappears mid-update | Kill the whole device process, do not restart | n/a (device gone) | `TIMED_OUT` via `timeoutConfig` |
| S7c | Dead device returns after timeout | Restart device after S7b | Rolls back unconfirmed trial; tolerates rejected status update | stays `TIMED_OUT` |
| S8 P1 to P10 | Power cut at each install stage | `maybe_crash(point)` | See 2.6 | See 2.6 |
| S9 | Bad release across 20 devices | Buggy fw, slow rollout, abort threshold | Few devices exposed | Job aborted (`CANCELED`) |

S7b and S7c run as one sequence (`S7bc`). S9 runs on AWS only. The local matrix therefore has 28 cases, counted in `tests/scenarios.yaml`, which is the source of truth.

### 2.6 Power interruption at each installation stage (S8)

Each point is a named crash location followed by a device restart. Trial policy: **one trial attempt** (`trial_attempts_left = 1`), so an interrupted trial is treated conservatively as unconfirmed.

| Point | Crash location | State on disk | After restart | Final device | Final job |
|---|---|---|---|---|---|
| P1 | `download_mid` | Partial temp file; state unchanged | Old slot runs; temp file discarded; job resumed | New version after retry | SUCCEEDED |
| P2 | `download_done` | Complete temp file, unverified | Same as P1 | New version after retry | SUCCEEDED |
| P3 | `write_mid` | Inactive slot partial; pointer old | Old slot runs; inactive slot ignored | New version after retry | SUCCEEDED |
| P4 | `write_done` | Inactive slot complete, not yet re-verified | Old slot runs; update retried | New version after retry | SUCCEEDED |
| P5 | `flip_tmp_written` | `state.tmp` written, rename not done | `.tmp` ignored and cleaned; old state authoritative | New version after retry | SUCCEEDED |
| P6 | `post_flip` | `TRIAL`, attempts left 1, new fw not yet started | Trial starts normally | New version (if healthy) | SUCCEEDED |
| P7 | `trial_mid` | `TRIAL`, attempts left 0, fw was running | Unconfirmed trial, so rollback | Old version | FAILED `TRIAL_INTERRUPTED` |
| P8 | `health_passed` | Health passed in memory only; state still `TRIAL`, 0 left | Unconfirmed, so rollback (conservative) | Old version | FAILED `TRIAL_INTERRUPTED` |
| P9 | `commit_tmp_written` | `state.tmp` has `STABLE`, rename not done | `.tmp` ignored; still `TRIAL`, so rollback | Old version | FAILED `TRIAL_INTERRUPTED` |
| P10 | `post_commit` | `STABLE`, new version; job still `IN_PROGRESS` | Device sees pending job whose version it already runs, reports SUCCEEDED without reinstalling (idempotent) | New version | SUCCEEDED |

P7 to P9 deliberately roll back a firmware that may have been fine. That is a documented tradeoff (decision 6): a power cut during trial costs one retry, in exchange for never committing something unconfirmed.

### 2.7 Test outputs
- Evidence logs, one per scenario: `docs/evidence/<id>.log` (local, from `make test-failures`) and `docs/evidence/aws/<id>.log` (real AWS, from `make test-e2e` and `scripts/fleet_demo.py`). Each holds the expected and observed outcome, the invariants, and the device's own log lines.
- `docs/RESULTS.md` and the README headline numbers, generated from those logs by `make results`. Nothing is typed by hand; a missing log shows as "not run".
- An optional terminal recording of the local failure run (`make demo`, stored as `docs/demo.cast`).

---

## 3. System architecture

```
  DEVELOPER MACHINE                              AWS CLOUD (created by Terraform)
 +--------------------+              +-----------------------------+
 | publish.py         |--(1) digest->| KMS  ECC P-256 (SIGN_VERIFY)|
 |  build fw vN       |<-signature---|  private key never exported |
 |  sha256 + manifest |              +-----------------------------+
 |                    |
 |                    |--(2) upload->+-----------------------------+
 |                    |              | S3  firmware bucket (private)|
 |                    |              |  releases/vN/fw.bin         |
 |                    |              |  releases/vN/manifest.json  |
 |                    |              |  releases/vN/manifest.sig   |
 |                    |              +--------------+--------------+
 |                    |                             | presigned URLs (via IAM role)
 |                    |--(3) create->+--------------v--------------+
 |                    |     job      | AWS IoT Jobs                |
 +--------------------+              |  rolloutConfig  (pace)      |
                                     |  abortConfig    (blast rad.)|
                                     |  timeoutConfig  (silence)   |
                                     +--------------+--------------+
                                                    | job documents
                                     +--------------v--------------+
                                     | AWS IoT Core                |
                                     |  MQTT broker (TLS + X.509)  |
                                     |  Device Shadow (reported v) |
                                     +-----+---------+---------+---+
                                           |         |         |
                         +-----------------+         |         +-----------------+
                         |                           |                           |
                 +-------v--------+          +-------v--------+          +-------v--------+
                 | device-001     |          | device-002     |   ...    | device-020     |
                 | (simulated)    |          | (simulated)    |          | (simulated)    |
                 +----------------+          +----------------+          +----------------+
                       thing group: fleet-a  (jobs target the group)
```

### Device internals (simulated)

```
 +--------------------------------------------------------------+
 | device process (one per simulated device)                    |
 |                                                              |
 |  +-------------------+     +------------------------------+  |
 |  | updater.py        |     | state.json  (atomic writes)  |  |
 |  |  - jobs client    |<--->|  active_slot:  A | B         |  |
 |  |  - downloader     |     |  version:      "1.0.0"       |  |
 |  |  - verifier       |     |  security_ver: 2             |  |
 |  |  - slot writer    |     |  active_image_sha256: "..."  |  |
 |  |  - health gate    |     |  status:  STABLE | TRIAL     |  |
 |  |  - faults.py      |     |  trial_attempts_left: 0 | 1  |  |
 |  +---------+---------+     +------------------------------+  |
 |            | starts + supervises (subprocess)                |
 |            v                                                 |
 |  +-------------------+      +-------------------+            |
 |  | slot_a/fw.py      |      | slot_b/fw.py      |            |
 |  |  ACTIVE  v1.0.0   |      |  INACTIVE         |            |
 |  +-------------------+      +-------------------+            |
 |                                                              |
 |  trusted_pubkey.pem  (a file in this simulation)             |
 +--------------------------------------------------------------+
```

**Invariant:** `state.json` is the only thing that decides which slot runs, and it changes in exactly one atomic step (write temp file, `fsync`, `os.replace`, `fsync` directory). Everything before that step touches only the inactive slot.

### State file
`state.json` holds: `active_slot`, `version`, `security_version`, `active_image_sha256`, `status` (`STABLE` or `TRIAL`), `trial_attempts_left`, plus two fields added during the build:
- `previous`: the slot, version and hash to roll back to, set when a trial starts.
- `pending_job`: the job ID, versions, the security version to apply at commit, and the **result** (`SUCCEEDED`, or `FAILED` with a reason). Recording the result in the same atomic write as the commit or rollback means a restart can always report the right outcome to the job, even if the first report was lost (P10) or the trial was interrupted (P7 to P9).

### Update state machine

```
        job received
 IDLE ----------------> DOWNLOADING
  ^                          | ok
  |                          v
  |                     VERIFYING ---- bad signature / hash / size / version ---> REJECTED
  |                          | ok                                          (job -> FAILED,
  |                          v                                              stay on old slot)
  |                     WRITING    (inactive slot only)
  |                          |
  |                          v
  |                     RE-VERIFY  (read slot back, hash it)  --- mismatch ---> REJECTED
  |                          | ok
  |                          v
  |                     SWITCHED   <--- single atomic commit point
  |                          |         (active=new, status=TRIAL, attempts_left=1)
  |                          v
  |                       TRIAL    (start new fw, health gate with deadline)
  |                      /          \
  |          healthy    /            \  unhealthy | crash | deadline | interrupted
  |                    v              v
  |             COMMITTED          ROLLED_BACK
  |       (status=STABLE,        (active=old slot,
  |        bump security_ver,     report FAILED + reason)
  |        job -> SUCCEEDED)
  |                  |                |
  +------------------+----------------+
```

### Update flow (happy path)
1. `publish.py` builds firmware vN, writes the manifest, signs it with KMS, uploads to S3, and creates an IoT Job.
2. The device asks for work with `start-next` (it polls; it does not subscribe to `notify-next`) and receives the job document. A job already `IN_PROGRESS` for the device is returned again, which is how an interrupted update is retried after a restart.
3. Device downloads the manifest, signature, and image through presigned URLs, in 512-byte HTTP range requests so a dropped connection resumes where it stopped.
4. Device verifies in order: manifest signature, `security_version >= stored`, image size, image SHA-256.
5. Device writes the image to the inactive slot, then **reads it back and re-hashes it** before trusting it.
6. Device flips `state.json` to the new slot with `status=TRIAL`.
7. Device starts the new firmware and runs the health gate (decision 4).
8. Pass: commit, update shadow, report `SUCCEEDED`. Fail: roll back, report `FAILED` with `statusDetails`.

---

## 4. Data formats

### Release manifest (this is what gets signed)
```json
{
  "name": "fw",
  "version": "1.1.0",
  "security_version": 3,
  "size": 2048,
  "sha256": "9f2c...e1",
  "created": "2026-11-12T10:00:00Z"
}
```
The signature is computed over the SHA-256 of the canonical JSON (sorted keys, no whitespace) and stored as `manifest.sig` (base64, DER-encoded ECDSA). The manifest contains the image hash, so one signature covers the image, the version, and the downgrade counter.

### IoT Job document
```json
{
  "operation": "firmware-update",
  "version": "1.1.0",
  "manifest_url":  "${aws:iot:s3-presigned-url:https://BUCKET.s3.amazonaws.com/releases/1.1.0/manifest.json}",
  "signature_url": "${aws:iot:s3-presigned-url:https://BUCKET.s3.amazonaws.com/releases/1.1.0/manifest.sig}",
  "image_url":     "${aws:iot:s3-presigned-url:https://BUCKET.s3.amazonaws.com/releases/1.1.0/fw.bin}"
}
```
The job needs a `presignedUrlConfig` (role ARN and expiry) so IoT can substitute the URLs. The role is created by Terraform.

### Job execution `statusDetails` (reported by device)
```json
{ "reason": "SIGNATURE_INVALID", "slot": "B", "from": "1.0.0", "to": "1.1.0" }
```
Reason codes: `SIGNATURE_INVALID`, `HASH_MISMATCH`, `SIZE_MISMATCH`, `DOWNGRADE_REJECTED`, `HEALTH_CHECK_FAILED`, `CLOUD_UNREACHABLE`, `TRIAL_TIMEOUT`, `TRIAL_INTERRUPTED`, plus `MANIFEST_INVALID` (signed but malformed, or version differs from the job) and `DOWNLOAD_FAILED` (artifact missing or unreadable). On success `statusDetails` carries only `slot`, `from` and `to`.

Verification failures are reported as `FAILED` (not `REJECTED`) so that `abortConfig` can count them; `REJECTED` is reserved for unsupported job operations (a path the tests do not exercise, so its behaviour against real Jobs is unverified).

### Shadow (reported)
```json
{ "state": { "reported": { "version": "1.0.0", "slot": "A", "status": "STABLE", "security_version": 2 } } }
```
The health gate's cloud heartbeat is also a shadow update (it adds `last_heartbeat` to `reported`), so it needs no extra topic or policy statement.

### MQTT topics used
```
$aws/things/<thing>/jobs/start-next                 (+ /accepted, /rejected replies)
$aws/things/<thing>/jobs/<jobId>/update             (+ /accepted, /rejected replies)
$aws/things/<thing>/shadow/update
```

---

## 5. Update safety mechanisms in the job (rollout, abort, timeout)

| Config | Purpose | Example for the demo |
|---|---|---|
| `jobExecutionsRolloutConfig.maximumPerMinute` | Pace of rollout; sets how many devices get a bad image before the first failure reports back | 4 devices per minute |
| `abortConfig` (failureType `ALL`, `CANCEL`) | Cancels the job when failures cross a threshold | 20% after at least 5 devices have executed |
| `timeoutConfig.inProgressTimeoutInMinutes` | Marks an execution `TIMED_OUT` when a device goes silent mid-update | 1 to 2 minutes (the minimum is 1 minute) |

Too fast a rollout defeats abort: every device has the bad image before the first failure is counted. The abort also cannot fire before `minNumberOfExecutedThings` devices have run, so that number is a floor on exposure. Tune pace and threshold together; S9 measures both a slow and a fast rollout (see `docs/RESULTS.md`). A staged rollout hands devices their job over several minutes, so the device has a `--watch` mode that keeps polling instead of checking once.

---

## 6. Infrastructure as code (Terraform)

All AWS infrastructure is created and destroyed by Terraform. Releases (jobs) are *not* infrastructure; they are runtime events created by `publish.py`.

```
 TERRAFORM (infra/terraform)       SCRIPTS (cloud/, scripts/)     RUNTIME (device/)
 ---------------------------       --------------------------     -----------------
 S3 bucket (private, versioned,    publish.py                     updater.py
   encrypted)                        build, sign, upload,           jobs client, state
 KMS ECC P-256 key + alias           create IoT Job                 machine, health gate
 IoT thing group + N things        gen_device_csrs.sh             faults.py (tests)
 IoT device policy                   device keys stay local
 IoT certificates (from CSRs)      run_scenarios.py
 IAM role for presigned URLs         failure matrix runner
 outputs: endpoint, bucket, key
```

### Layout
```
infra/terraform/
  versions.tf        # provider + terraform version pins
  variables.tf       # region, device_count (default 20), name_prefix
  s3.tf              # bucket, public access block, versioning, encryption
  kms.tf             # signing key + alias
  iot.tf             # thing group, things, policy, certificates, attachments
  iam.tf             # role IoT assumes to presign S3 URLs
  outputs.tf         # iot endpoint, bucket, key id, role arn, cert PEMs (marked sensitive)
  terraform.tfvars.example
```

### Resources
| Resource | Notes |
|---|---|
| `aws_s3_bucket` + public access block, versioning, SSE | Private; devices reach it only through expiring presigned URLs. `force_destroy = true` for easy teardown. |
| `aws_kms_key` (`SIGN_VERIFY`, `ECC_NIST_P256`) + `aws_kms_alias` | 7-day deletion window. Asymmetric keys do not auto-rotate. |
| `aws_iot_thing_group`, `aws_iot_thing` (`for_each`) | Jobs target the group. |
| `aws_iot_policy` | Per-thing least privilege using the `${iot:Connection.Thing.ThingName}` policy variable. |
| `aws_iot_certificate` (from CSR), policy and principal attachments, group membership | Certificates are created from locally generated CSRs. |
| `aws_iam_role` for IoT | Trust `iot.amazonaws.com` with a source-account condition; allows `s3:GetObject` on `releases/*` only. |
| `data.aws_iot_endpoint` | Exposed as an output for the device config. |

### Key snippets

```hcl
# kms.tf
resource "aws_kms_key" "release_signing" {
  description              = "failsafe-ota release manifest signing"
  key_usage                = "SIGN_VERIFY"
  customer_master_key_spec = "ECC_NIST_P256"
  deletion_window_in_days  = 7
}

resource "aws_kms_alias" "release_signing" {
  name          = "alias/${var.name_prefix}-release-signing"
  target_key_id = aws_kms_key.release_signing.key_id
}
```

```hcl
# iot.tf (device identities: private keys never enter Terraform state)
locals {
  devices = toset([for i in range(1, var.device_count + 1) : format("device-%03d", i)])
}

resource "aws_iot_thing" "device" {
  for_each = local.devices
  name     = each.key
}

resource "aws_iot_certificate" "device" {
  for_each = local.devices
  csr      = file("${path.root}/../../build/devices/${each.key}/device.csr")
  active   = true
}

resource "aws_iot_policy_attachment" "device" {
  for_each = local.devices
  policy   = aws_iot_policy.device.name
  target   = aws_iot_certificate.device[each.key].arn
}

resource "aws_iot_thing_principal_attachment" "device" {
  for_each  = local.devices
  thing     = aws_iot_thing.device[each.key].name
  principal = aws_iot_certificate.device[each.key].arn
}
```

```hcl
# iot.tf (policy gotcha: escape the IoT policy variable so Terraform does not interpolate it)
resource "aws_iot_policy" "device" {
  name = "${var.name_prefix}-device"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = "iot:Connect",
        Resource = "arn:aws:iot:${var.region}:${local.account_id}:client/$${iot:Connection.Thing.ThingName}" },
      { Effect = "Allow", Action = ["iot:Publish", "iot:Receive"],
        Resource = "arn:aws:iot:${var.region}:${local.account_id}:topic/$aws/things/$${iot:Connection.Thing.ThingName}/*" },
      { Effect = "Allow", Action = "iot:Subscribe",
        Resource = "arn:aws:iot:${var.region}:${local.account_id}:topicfilter/$aws/things/$${iot:Connection.Thing.ThingName}/*" }
    ]
  })
}
```

### Usage
```bash
scripts/gen_device_csrs.sh 20        # local private keys + CSRs under build/devices/
cd infra/terraform
terraform init
terraform plan -out tf.plan
terraform apply tf.plan
terraform output -json > ../../build/tf-outputs.json
cd ../.. && scripts/export_certs.sh  # writes certificate PEMs next to each device key
python -m cloud.publish export-pubkey   # the device's trusted key, exported from KMS
make test-e2e                        # scenarios against real AWS
python scripts/fleet_demo.py         # S9
make results
make tf-destroy                      # terraform destroy
```

### Terraform decisions
- **T1, scope:** Terraform owns long-lived infrastructure; `publish.py` owns releases and jobs, because a release is an event with a lifecycle, not a resource to keep in sync.
- **T2, keys stay out of state:** device private keys are generated locally and only CSRs are passed to Terraform, so the state file holds certificates and resource ARNs but no device private keys. The state is still treated as sensitive and never committed (`*.tfstate*` is git-ignored). The CSRs use RSA-2048 keys, and `gen_device_csrs.sh` never regenerates an existing key or CSR, because a changed CSR would make Terraform replace the certificate. (The alternative, letting Terraform generate the key pair, would put private keys in state.)
- **T3, state:** local backend for the project. An S3 backend with locking is the next step for a team; noted under future work.
- **T4, teardown:** `terraform destroy` removes everything; the KMS key enters its 7-day deletion window.
- **T5, hygiene:** a pinned provider version range and a committed lock file; `terraform fmt -check` and `terraform validate` run in CI. A `tflint` or `checkov` scan was considered and not added.

---

## 7. What is simulated and what is real

Standalone copies of this section and of the limits below are [SIMULATED-VS-REAL.md](SIMULATED-VS-REAL.md) and [LIMITATIONS.md](LIMITATIONS.md).

### Be precise in the README
| Component | In this project | Real-world equivalent |
|---|---|---|
| Device | Python process per simulated device | Microcontroller or embedded Linux board |
| A/B slots | Two directories, `slot_a/` and `slot_b/` | Two flash regions or partitions managed by a bootloader |
| "Which slot runs" | `state.json`, updated atomically with `os.replace` | Bootloader state (image trailer flags, boot environment variables) |
| "Boot" | Updater starts the slot's `fw.py` as a subprocess | Bootloader jumps into the selected image |
| Trial and commit | `status=TRIAL`, `trial_attempts_left`, commit writes `STABLE` | Test image + confirm call (MCUboot) or `bootcount` / `upgrade_available` (U-Boot) |
| Image verification | Done by `updater.py` against a public key file | Done by the bootloader against a key it protects |
| Power cut | `os._exit` at named points | Real power loss, flash erase and write behavior |
| Cloud side | **Real:** IoT Core, Jobs, Shadow, S3, KMS, IAM, Terraform | Same |

### What the README will say and will not say
| Will say | Will not say |
|---|---|
| "Update protocol and failure handling, tested against a simulated A/B device" | "Implemented a bootloader" |
| "Python A/B slot simulator" | "Real A/B firmware partitions" or "secure boot" |
| "Atomic commit point via write, fsync, rename" | "Power-loss safe on real flash" |
| "Signed manifest verified before install; downgrade protection" | "Hardware-rooted trust" |
| "Fault injection at named crash points" | "Tested on real hardware" (unless a board is actually used) |

### What the simulation does not model
- Flash semantics (erase blocks, write granularity, wear, partial page writes).
- Loss of un-fsynced data on real power loss (see 2.3).
- A local attacker who can edit `state.json` or the public key file; a real device protects these in the bootloader, ROM, or a secure element.
- Watchdogs, boot ROM, secure boot chain.

### Porting path to a real bootloader (conceptual)
This is a conceptual mapping, not an implementation. Verify details against the current MCUboot and U-Boot documentation before quoting specifics.

| This project | MCUboot (microcontrollers) | U-Boot A/B (embedded Linux) |
|---|---|---|
| `slot_a/`, `slot_b/` | Primary and secondary image slots (swap modes), or two XIP slots (direct-xip, closest to true A/B) | Two kernel/rootfs partitions |
| `state.json` active slot and status | Swap state kept in the image trailer | U-Boot environment variables (for example boot partition, `upgrade_available`) |
| `TRIAL` with one attempt | "Test" swap: runs once, reverts if not confirmed | `bootcount` / `bootlimit` with `upgrade_available=1` |
| Commit | Application marks the image confirmed | Userspace clears `upgrade_available` and resets `bootcount` |
| Rollback on unconfirmed | Bootloader reverts the swap on the next reset | `altbootcmd` switches to the other partition |
| Signed manifest, checked by `updater.py` | Signature TLV in the image (ECDSA P-256 supported), checked by the bootloader | FIT image signatures / verified boot |
| `security_version` | Security counter for rollback protection | Platform-specific rollback index |
| Atomic `os.replace` | Swap status trailer designed to survive power loss mid-swap | Redundant environment copies |

**Port steps**
1. Replace the slot directories with flash partitions and the `state.json` logic with bootloader calls (mark pending, confirm).
2. Move verification from `updater.py` into the bootloader; the updater only downloads and stages.
3. Change the signing step: the bootloader expects its own image format, so `publish.py` would call the bootloader's image tool (for example `imgtool` for MCUboot) instead of signing a JSON manifest. KMS can still protect the key but needs integration glue.
4. Keep the cloud side unchanged: IoT Jobs, rollout, abort, timeout, shadow reporting, Terraform.
5. Re-run the same scenario catalog on hardware or an emulator, injecting power cuts at flash write boundaries with a relay or by resetting the emulator.

---

## 8. Design decisions

### Decision 1: A/B slots instead of in-place update
Two slots; update the inactive one; switch with one atomic pointer write. In-place leaves no good image if power fails mid-write. Cost: double the storage.

### Decision 2: Sign the manifest, not only the image
KMS signs the SHA-256 of the canonical manifest, which contains the image hash, version, and `security_version`. Signing only the image would let an attacker pair a valid image with altered metadata. S3c tests exactly this. Alternative noted: AWS Signer with IoT code-signing jobs.

### Decision 3: Monotonic `security_version` for downgrade protection
The device rejects any release with a lower `security_version` than its committed value, even if validly signed. `version` is for humans and may go down (S4b) when the release team intentionally rolls back, as long as the security floor holds. The stored value is raised only at commit, never during a trial, so a rollback never raises the floor.

### Decision 4: What "healthy" means
Healthy only if **all** hold within the trial deadline: the process stays alive for a minimum window (so firmware that passes and then dies seconds later is not committed), a local self-test passes, and the device can still connect to IoT Core and publish a heartbeat. The connectivity check exists because firmware that breaks connectivity is the classic way to strand a remote device. **The check retries within the window**, so a short blip (S6c) does not cause a false rollback, while a long outage (S6d) does.

### Decision 5: Silence is a failure
Both layers treat "no confirmation" as failure. On the device, an unconfirmed `TRIAL` with no attempts left rolls back. In the cloud, `timeoutConfig` turns a vanished device into `TIMED_OUT`, which `abortConfig` can count. A device that never reports is the one you most need to treat as failed.

### Decision 6: Conservative trial policy
One trial attempt. A power cut during trial (P7 to P9) rolls back and costs one retry. Raising the attempt limit to 2 would tolerate a single power cut but gives a crash-looping image a second run. Chosen conservative; configurable and measured.

### Decision 7: Atomic commit and verify-after-write
Write temp file, `fsync`, `os.replace`, `fsync` directory; `state.json` is the only commit point. After writing the inactive slot, read it back and re-hash it before switching, so a torn slot write is never promoted.

### Decision 8: Staged rollout and automatic abort
Slow `rolloutConfig` plus an `abortConfig` threshold define blast radius. A low threshold means fewer bad installs but more false aborts from one flaky device. S9 records the numbers (`docs/RESULTS.md`). The abort cannot fire before its minimum number of executed devices, so that number is a floor on exposure.

### Decision 9: Identity and exposure
Per-device X.509 cert, least-privilege policy by thing name, S3 reachable only through expiring presigned URLs, signing key only in KMS, device private keys never in Terraform state.

Short per-decision notes with the scenarios that prove each one are in [decisions/](decisions/).

---

## 9. Repository layout

```
failsafe-ota/
  README.md                  # failure matrix and headline numbers first
  Makefile                   # test-unit, test-failures, test-e2e, results, demo, tf-init/apply/destroy
  requirements.txt  pytest.ini  .gitignore
  docs/
    design.md                # this document
    RESULTS.md               # generated by scripts/make_results.py
    SIMULATED-VS-REAL.md     # what is simulated, what is real, porting path
    LIMITATIONS.md           # what the project does not prove
    decisions/               # one short note per decision
    evidence/                # per-scenario logs: local, and aws/ for real AWS
  device/
    updater.py               # jobs client + state machine (+ --watch mode)
    slots.py                 # slots, atomic state writes, slot writes
    verify.py                # signature, schema, downgrade, size, hash
    health.py                # health gate (alive, self-test, cloud heartbeat)
    faults.py                # test-only fault injection hooks
    transport.py             # exceptions shared by both transports
    aws_transport.py         # real IoT Jobs/Shadow over MQTT, firmware over HTTPS
    provision.py             # create or reset a simulated device directory
    firmware/                # fake fw: good, crash_now, crash_later, no_cloud, hang, selftest_fail
  cloud/
    publish.py               # build, KMS sign, S3 upload, create job (rollout/abort/timeout)
    release.py               # release builder, with tamper modes for the tests
    signing.py               # LocalSigner (tests) and KmsSigner
    fake_jobs.py             # file-backed fake Jobs/Shadow/S3 for L2
  infra/terraform/           # see section 6
  scripts/
    gen_device_csrs.sh       # device keys + CSRs (kept local)
    export_certs.sh          # certificates from Terraform outputs, Amazon root CA
    fleet_demo.py            # S9: 20 devices, bad release, rollout + abort
    make_results.py          # RESULTS.md and README headline from the evidence logs
  tests/
    scenarios.yaml           # expected result per scenario
    harness.py               # runs a scenario, checks invariants I1 to I7
    run_scenarios.py         # runs the local matrix, writes evidence + README matrix
    test_verify.py  test_state_atomicity.py  test_publish.py
    test_aws_transport.py  test_watch.py  test_make_results.py     # L1
    test_scenarios_local.py  # L2: full matrix + all crash points
    test_e2e_aws.py          # L3: opt-in, real AWS
  build/                     # git-ignored: device keys, certificates, Terraform outputs, simulated devices
  .github/workflows/ci.yml   # L1 + L2, terraform fmt/validate
```

---

## 10. Build plan (about 4 to 5 days, ~25 hours)

Checked boxes are done.

This is longer than a bare-bones version because failure testing and Terraform are now deliverables.

### Day 1: device core and fault hooks (~6 h)
- [x] Slot model, `state.json`, atomic write helper, leftover `.tmp` cleanup
- [x] `verify.py` (signature, hash, size, downgrade) with a local ECDSA keypair
- [x] State machine through `TRIAL`, `COMMITTED`, `ROLLED_BACK`, including read-back verify
- [x] `faults.py` with named crash points P1 to P10
- [x] Fake firmware variants (good, crash-now, crash-later, no-cloud, hang)

### Day 2: local scenario matrix (~5 h)
- [x] `fake_jobs.py` transport and `tests/scenarios.yaml`
- [x] Invariant checker (I1 to I7)
- [x] S1 to S8 passing locally in `run_scenarios.py`
- [x] CI runs L1 and L2

### Day 3: Terraform and AWS integration (~6 h)
- [x] Terraform: S3, KMS, IoT things/group/policy, CSR-based certs, IAM role, outputs
- [x] `gen_device_csrs.sh`, `export_certs.sh`
- [x] `publish.py`: manifest, KMS sign, upload, create job with `presignedUrlConfig`
- [x] Device wired to real Jobs topics, `statusDetails`, shadow reporting
- [x] S1 to S4 pass end to end on AWS

### Day 4: cloud failure cases and fleet (~5 h)
- [x] S5, S6, S7 on AWS (S7b and S7c need a 1 to 2 minute job timeout)
- [x] Representative S8 subset (P4, P7, P10) through real Jobs
- [x] 20-device fleet, `rolloutConfig` and `abortConfig` (S9); record devices exposed

### Day 5: evidence and writeup (~4 h)
- [x] Generate `RESULTS.md` and collect evidence logs
- [ ] Record the terminal run (optional: `make demo`)
- [x] Decision notes, README with failure matrix first, diagrams
- [x] Terraform `fmt` / `validate` in CI (`tflint` / `checkov` not added)

**If time runs short, cut in this order:** (1) S9 fleet demo, (2) the L3 S8 subset, (3) `checkov`, (4) S2b, S3b, S6c, S6d variants. Do not cut the L2 matrix, the invariants, or Terraform.

---

## 11. Results

Results are generated, not written here. `make results` builds [RESULTS.md](RESULTS.md) from the evidence logs and fills the README's headline numbers:

- Local failure matrix (simulated cloud): cases passed.
- Real AWS: scenarios passed.
- Power-cut points that leave no unrunnable device (S8, P1 to P10).
- Bad fleet release: devices that got the bad image, at a slow and at a fast rollout rate, and the job's final status.
- Time from bad install to a reported rollback.

RESULTS.md also lists every scenario with its expected outcome and a link to its log, local and AWS side by side. A scenario with no log shows as "not run".

---

## 12. Cost and teardown

- IoT Core messages, Jobs, S3, and Terraform itself cost pennies at this scale.
- A KMS key costs about a dollar per month prorated, plus a small per-request fee.
- **Teardown:** `make tf-destroy` (`terraform destroy`). The KMS key is scheduled for deletion (7-day window set in Terraform). Delete local `build/devices/` private keys.

---

## 13. Design FAQ

- *"What if power dies mid-write?"* Only the inactive slot is touched until one atomic pointer write; the 10-point crash table shows each outcome. In the simulator I can show ordering; real flash durability needs hardware testing.
- *"How do you stop downgrade attacks?"* Monotonic `security_version` inside the signed manifest (S4a), while allowing intentional `version` rollbacks (S4b).
- *"What makes firmware healthy?"* Alive, self-test passes, and still reaches the cloud, with retries for short blips (S6c vs S6d).
- *"What if a device just disappears?"* Silence counts as failure on-device and via job timeout (S7).
- *"Why roll back on a power cut during trial?"* Conservative policy; tradeoff and the attempt-limit knob are documented.
- *"Why Terraform for infra but a script for releases?"* Infra is long-lived state; a release is an event.
- *"Is this a real bootloader?"* No: it's a Python A/B simulator; section 7 maps each piece to MCUboot and U-Boot and lists what the simulation doesn't model.

---

## 14. Future work

- Run the device side on a real board with MCUboot or U-Boot A/B and repeat the scenario catalog with real power cuts.
- A crash-consistent test file layer that drops un-fsynced writes.
- AWS Signer with IoT code-signing jobs instead of manifest verification in `updater.py`.
- Remote Terraform state (S3 backend with locking), CI-driven `plan`.
- Delta updates, encrypted images, multi-signer release approval.
- Per-wave health analysis before proceeding to the next rollout wave.
- Real network fault injection for the AWS scenarios (today the S6 outages are injected inside the device's transport).
- Run the fleet across several machines, and verify how real Jobs treats `REJECTED` and in-flight executions when a job is aborted.
- A `tflint` or `checkov` pass over the Terraform.

---

## 15. As built: changes from the original plan

| Area | Plan | As built | Why |
|---|---|---|---|
| Local cases | about 35 | 28 | S7b and S7c are one sequence (`S7bc`); S9 is AWS-only; the S3b and S3c variants are counted individually |
| AWS cases | about 15 | 21, plus the S9 fleet runs | every no-fault scenario, plus S6b to S6d, S7bc and S8 P4, P7, P10 |
| State file | six fields | adds `previous` and `pending_job` | a restart must know where to roll back to and which outcome to report (section 3) |
| Health gate | alive, self-test, heartbeat | also a minimum-alive window | firmware that passes then dies seconds later (S5b) must not be committed |
| Reason codes | eight | adds `MANIFEST_INVALID`, `DOWNLOAD_FAILED` | a signed but malformed manifest; a missing artifact |
| Job pickup | `notify-next`, then `start-next` | `start-next` polling, plus a `--watch` mode | simpler; a restarted device gets its `IN_PROGRESS` job back (proved by the S8 and S7 AWS runs); staged rollouts need devices that keep polling |
| Timings | S5b crashes after 3 s | 0.4 s, with short health windows | the whole local matrix runs in well under a minute |
| S6 on AWS | `net_fault` | injected in the device's transport, not real packet loss | no safe way to cut a real connection mid-test |
| Device certificates | from CSRs | RSA-2048 CSRs, never regenerated once created | CSR-based creation is supported for RSA; a changed CSR would replace the certificate |
| Results report | written by the test runner | `scripts/make_results.py` from evidence logs | one source of truth for the README and RESULTS.md |
| Terraform scan | optional `tflint` / `checkov` | `fmt` and `validate` only | cut for time, as the plan allowed |
| Certificate output | PEMs | marked `sensitive` | the AWS provider marks the attribute sensitive |