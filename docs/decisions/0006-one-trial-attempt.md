# 0006: Conservative trial policy (one attempt)

**Decision.** A new image gets one trial run. If power is cut during the trial (P7 to P9) the next
start rolls back, and the update costs one retry.

**Why.** Allowing two attempts would tolerate a single power cut but gives a crash-looping image a
second run. The conservative default protects the device; the retry is cheap.

**Cost.** A power cut during a good update causes a rollback and needs a re-send.

**Evidence.** S8 P6 (cut right after the switch still gets its one run and succeeds), P7 to P9 (cut
during trial, health pass and commit write all roll back), P10 (cut right after commit succeeds).
`trial_attempts_left` is a single setting.
