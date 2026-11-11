# Failure results (L2, local fake Jobs transport)

**Cases passed: 28 / 28**

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
