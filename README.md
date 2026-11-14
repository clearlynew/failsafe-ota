# failsafe-ota

A failure-first over-the-air update protocol for AWS IoT. The point is not that updates work, but
that when they fail (tampered image, forged signature, downgrade attack, crashing or silent
firmware, lost connectivity, power cut at any install stage, a bad release across a fleet) the
device ends up on a known-good image, and that this is **tested**, not claimed.

The device is a Python A/B-slot **simulation**, not a bootloader. The cloud side is real: IoT Core
Jobs and Shadow, S3, KMS, IAM, all in Terraform. See
[what is simulated and what is real](docs/SIMULATED-VS-REAL.md) and
[known limitations](docs/LIMITATIONS.md).

## Headline results

<!-- HEADLINE:START -->
- **Local failure matrix (simulated cloud):** 28 / 28 cases pass
- **Real AWS (KMS, S3, IoT Jobs, Shadow):** 21 / 21 scenarios pass
- **Power-cut points that leave no unrunnable device (S8, P1 to P10):** 10 / 10
- **Bad fleet release (4/min, abort at 20.0% after 5 executed):** 5 / 20 devices got the bad image; job CANCELED after 78s; devices left on it: 0
- **Bad fleet release (20/min, abort at 20.0% after 5 executed):** 9 / 20 devices got the bad image; job CANCELED after 21s; devices left on it: 0
- **Bad install to rollback reported (average, slowest-rollout run):** 5.7 s
<!-- HEADLINE:END -->

Full table with links to every log: [docs/RESULTS.md](docs/RESULTS.md).

## Failure matrix (local, simulated cloud)

<!-- MATRIX:START -->
**28 / 28 local failure cases pass**

| ID | Scenario | Expected | Observed | Invariants I1-I7 | Pass |
|---|---|---|---|---|---|
| S1 | Good update (baseline) | SUCCEEDED, v1.1.0 | SUCCEEDED, v1.1.0 | all | PASS |
| S2a | Tampered image | FAILED `HASH_MISMATCH`, v1.0.0 | FAILED `HASH_MISMATCH`, v1.0.0 | all | PASS |
| S2b | Truncated image | FAILED `SIZE_MISMATCH`, v1.0.0 | FAILED `SIZE_MISMATCH`, v1.0.0 | all | PASS |
| S3a | Wrong-key signature | FAILED `SIGNATURE_INVALID`, v1.0.0 | FAILED `SIGNATURE_INVALID`, v1.0.0 | all | PASS |
| S3b-missing | Missing signature file | FAILED `SIGNATURE_INVALID`, v1.0.0 | FAILED `SIGNATURE_INVALID`, v1.0.0 | all | PASS |
| S3b-garbled | Corrupt signature file | FAILED `SIGNATURE_INVALID`, v1.0.0 | FAILED `SIGNATURE_INVALID`, v1.0.0 | all | PASS |
| S3c-sv | Manifest security_version edited after signing | FAILED `SIGNATURE_INVALID`, v1.0.0 | FAILED `SIGNATURE_INVALID`, v1.0.0 | all | PASS |
| S3c-sha | Manifest sha256 edited after signing | FAILED `SIGNATURE_INVALID`, v1.0.0 | FAILED `SIGNATURE_INVALID`, v1.0.0 | all | PASS |
| S4a | Downgrade attack (validly signed | FAILED `DOWNGRADE_REJECTED`, v1.0.0 | FAILED `DOWNGRADE_REJECTED`, v1.0.0 | all | PASS |
| S4b | Allowed rollback of version (same security_version) | SUCCEEDED, v1.0.5 | SUCCEEDED, v1.0.5 | all | PASS |
| S5a | Firmware crashes at start | FAILED `HEALTH_CHECK_FAILED`, v1.0.0 | FAILED `HEALTH_CHECK_FAILED`, v1.0.0 | all | PASS |
| S5b | Firmware crashes mid-trial | FAILED `HEALTH_CHECK_FAILED`, v1.0.0 | FAILED `HEALTH_CHECK_FAILED`, v1.0.0 | all | PASS |
| S6a | New firmware cannot reach cloud | FAILED `CLOUD_UNREACHABLE`, v1.0.0 | FAILED `CLOUD_UNREACHABLE`, v1.0.0 | all | PASS |
| S6b | Network drops mid-download (resumes) | SUCCEEDED, v1.1.0 | SUCCEEDED, v1.1.0 | all | PASS |
| S6c | Short outage during trial (tolerated) | SUCCEEDED, v1.1.0 | SUCCEEDED, v1.1.0 | all | PASS |
| S6d | Long outage during trial (rolled back) | FAILED `CLOUD_UNREACHABLE`, v1.0.0 | FAILED `CLOUD_UNREACHABLE`, v1.0.0 | all | PASS |
| S7a | Firmware hangs and never confirms | FAILED `TRIAL_TIMEOUT`, v1.0.0 | FAILED `TRIAL_TIMEOUT`, v1.0.0 | all | PASS |
| S7bc | Device disappears; job TIMED_OUT; device returns and recovers | TIMED_OUT, v1.0.0 | TIMED_OUT, v1.0.0 | all | PASS |
| S8-P1 | Power cut at download_mid | SUCCEEDED, v1.1.0 | SUCCEEDED, v1.1.0 | all | PASS |
| S8-P2 | Power cut at download_done | SUCCEEDED, v1.1.0 | SUCCEEDED, v1.1.0 | all | PASS |
| S8-P3 | Power cut at write_mid | SUCCEEDED, v1.1.0 | SUCCEEDED, v1.1.0 | all | PASS |
| S8-P4 | Power cut at write_done | SUCCEEDED, v1.1.0 | SUCCEEDED, v1.1.0 | all | PASS |
| S8-P5 | Power cut at flip_tmp_written | SUCCEEDED, v1.1.0 | SUCCEEDED, v1.1.0 | all | PASS |
| S8-P6 | Power cut at post_flip | SUCCEEDED, v1.1.0 | SUCCEEDED, v1.1.0 | all | PASS |
| S8-P7 | Power cut at trial_mid | FAILED `TRIAL_INTERRUPTED`, v1.0.0 | FAILED `TRIAL_INTERRUPTED`, v1.0.0 | all | PASS |
| S8-P8 | Power cut at health_passed | FAILED `TRIAL_INTERRUPTED`, v1.0.0 | FAILED `TRIAL_INTERRUPTED`, v1.0.0 | all | PASS |
| S8-P9 | Power cut at commit_tmp_written | FAILED `TRIAL_INTERRUPTED`, v1.0.0 | FAILED `TRIAL_INTERRUPTED`, v1.0.0 | all | PASS |
| S8-P10 | Power cut at post_commit | SUCCEEDED, v1.1.0 | SUCCEEDED, v1.1.0 | all | PASS |
<!-- MATRIX:END -->

Seven checks run after **every** scenario, not only the pass/fail result: the active slot's hash
matches the state file, the state file always parses, only signed images are ever active, the
security floor never decreases, the device is never left mid-trial, the job reports the right
outcome, and the cloud's idea of the version matches the device.

## How an update works

1. Fetch the manifest and signature; verify the signature, then the downgrade floor.
2. Download the image; verify size and SHA-256.
3. Write it to the **inactive** slot, read it back, re-hash it.
4. One atomic write (`state.json`) switches the active slot and starts a trial.
5. Health gate: the new image must stay alive, pass its self-test and still reach the cloud.
6. Commit (raise the security floor) or roll back; report the outcome to the job; update the shadow.

Power can be cut at any of ten named points in that sequence (S8). Design notes live in
[docs/decisions/](docs/decisions/) and the full design in [docs/design.md](docs/design.md).

## Run it locally (no AWS needed)

Python 3.10 or newer; Linux, macOS or WSL.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q                          # unit tests + the 28-case local matrix (~35 s)
make test-failures                 # re-run the matrix, rewrite the evidence logs and matrix above
make results                       # regenerate docs/RESULTS.md and the headline numbers
```

## Run it on AWS (optional; costs pennies)

Needs an AWS account with credentials configured, Terraform and the AWS CLI.

```bash
scripts/gen_device_csrs.sh 20              # keys + CSRs stay in build/ (gitignored)
make tf-init && make tf-apply              # S3, KMS, IoT things/policy/certs, IAM
(cd infra/terraform && terraform output -json > ../../build/tf-outputs.json)
scripts/export_certs.sh
python -m cloud.publish export-pubkey      # the device's trusted key, from KMS
make test-e2e                              # the scenarios against real AWS (~10 min)
python scripts/fleet_demo.py               # S9: bad release across 20 devices
make results
make tf-destroy                            # tear it all down
```

The KMS key costs about a dollar a month, prorated; the rest is pennies at this scale. Never commit
anything under `build/` (device private keys) or any `*.tfstate` file.

## Layout

| Path | Role |
|---|---|
| `device/` | Updater state machine, A/B slots, verification, health gate, fault hooks, real AWS transport |
| `cloud/` | Release builder and signers (local and KMS), `publish.py`, the file-backed fake cloud |
| `infra/terraform/` | All AWS resources |
| `scripts/` | Device CSRs and certificates, the fleet demo, the results generator |
| `tests/` | Scenario catalog (`scenarios.yaml`), harness, unit tests, opt-in AWS tests |
| `docs/` | Design, decisions, results, evidence logs, limitations |

## Design decisions

[A/B slots](docs/decisions/0001-ab-slots.md) ·
[Sign the manifest](docs/decisions/0002-sign-the-manifest.md) ·
[Security version](docs/decisions/0003-security-version.md) ·
[What healthy means](docs/decisions/0004-what-healthy-means.md) ·
[Silence is failure](docs/decisions/0005-silence-is-failure.md) ·
[One trial attempt](docs/decisions/0006-one-trial-attempt.md) ·
[Atomic commit](docs/decisions/0007-atomic-commit-and-verify-after-write.md) ·
[Rollout and abort](docs/decisions/0008-staged-rollout-and-abort.md) ·
[Identity and exposure](docs/decisions/0009-identity-and-exposure.md)

Terminal recording of the full local failure run: `docs/demo.cast` (`asciinema play docs/demo.cast`).