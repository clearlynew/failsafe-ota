# 0004: What "healthy" means

**Decision.** A new image is healthy only if all three hold inside the trial deadline: the process
stays alive for a minimum window, it reports a passing self-test, and the device can still publish
a heartbeat to the cloud. The heartbeat retries within the window.

**Why.** Firmware that breaks connectivity is the classic way to strand a remote device, so being
alive is not enough. Retrying means a short outage does not cause a false rollback.

**Cost.** A slower commit (the minimum-alive window) and a self-test that is only as good as the
firmware's own report. In this project the self-test is a line printed by a fake firmware.

**Evidence.** S5a and S5b (crash at start and mid-trial), S6a (cannot reach the cloud), S6c (short
outage tolerated), S6d (long outage rolled back), S7a (hang). Reasons reported: `HEALTH_CHECK_FAILED`,
`CLOUD_UNREACHABLE`, `TRIAL_TIMEOUT`.
