# 0008: Staged rollout and automatic abort

**Decision.** Releases to a group use a slow `maximumPerMinute` rollout plus an `abortConfig` that
cancels the job when failures cross a percentage after a minimum number of devices have executed.

**Why.** Pace and threshold together define the blast radius. The abort cannot fire before
`minNumberOfExecutedThings` devices have run, so exposure is at least that number, and a rollout
faster than the abort can react defeats it entirely.

**Cost.** A low threshold stops a bad release sooner but can abort on one flaky device.

**Evidence.** S9 runs a bad release across 20 simulated devices at a slow and a fast rate. The
measured numbers are in `docs/RESULTS.md`.
