# 0005: Silence is a failure

**Decision.** Both layers treat "no confirmation" as failure. On the device, an unconfirmed trial
with no attempts left is rolled back on the next start. In the cloud, a job `timeoutConfig` turns a
vanished device into `TIMED_OUT`. A device that comes back after its job timed out tolerates AWS
refusing its late status update.

**Why.** A device that never reports is the one you most need to treat as failed.

**Evidence.** S7a (hang), S7b/S7c (device killed mid-trial, AWS times the job out, device restarts,
rolls back and logs `job update rejected (tolerated)`), S8 P7 to P9 (`TRIAL_INTERRUPTED`).
