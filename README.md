# failsafe-ota

A failure-first OTA update protocol for AWS IoT. Devices are **simulated** (Python A/B slot model);
this is not a bootloader. Full design: [docs/design.md](docs/design.md).

## Failure results

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

Per-scenario logs: `docs/evidence/`. Regenerate with `make test-failures`.

## Run it on your machine

Needs Python 3.10+ (tested on 3.12). No AWS account needed for this stage.

```bash
cd failsafe-ota
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

make test-unit                     # L1: verification + atomic write tests (~1 s)
make test-failures                 # L2: full scenario matrix, writes docs/RESULTS.md (~15 s)
pytest -q                          # everything, via pytest
pytest -q -k S8-P7                 # a single scenario
```
On Windows without `make`, run the `python -m ...` commands from the Makefile directly.

## What exists so far (Day 1-2 of the build plan)

| Path | Role |
|---|---|
| `device/updater.py` | Jobs client + state machine (download, verify, write, flip, trial, commit/rollback) |
| `device/slots.py` | A/B slots and the single atomic commit (`state.json`: tmp, fsync, replace, fsync dir) |
| `device/verify.py` | Signature, schema, downgrade floor, size, hash |
| `device/health.py` | Health gate: alive + self-test + cloud heartbeat, with a deadline |
| `device/faults.py` | Crash points (`os._exit(137)`) and network blackholes, env-var driven |
| `device/firmware/` | Fake firmware: good, crash_now, crash_later, no_cloud, hang, selftest_fail |
| `cloud/fake_jobs.py` | File-backed fake of IoT Jobs/Shadow/S3 so crashes survive across processes |
| `cloud/release.py`, `signing.py` | Build + sign releases locally (ECDSA P-256), with 7 tamper modes |
| `tests/scenarios.yaml` | Expected outcome for every scenario |
| `tests/harness.py` | Runs each scenario in subprocesses and checks invariants I1-I7 |

## Not built yet (Day 3-5)

- `infra/terraform/` (S3, KMS, IoT things/policy/certs, IAM)
- `cloud/publish.py` (KMS signing, real S3 upload, real IoT Job with rollout/abort/timeout)
- Real IoT transport in the device (`awsiotsdk`) and the L3 end-to-end tests
- S9 fleet abort demo

The device talks to the cloud only through the transport interface in `device/transport.py`
and the methods on `FakeJobs` (`start_next`, `update_job`, `fetch`, `heartbeat`, `update_shadow`),
so the AWS version is a drop-in class with the same methods.

## Known limitation

`os._exit` proves write *ordering* and the commit point, not durability against a real power cut
(OS page cache). See design section 2.3.
