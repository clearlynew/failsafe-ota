# 0003: Monotonic `security_version` for downgrade protection

**Decision.** The device rejects any release whose `security_version` is below its committed value,
even if validly signed. The stored value is raised only at commit, never during a trial, so a
rollback never ratchets the floor up.

**Why.** `version` is for humans and may go down when the release team rolls back on purpose; the
security floor is what must never go down.

**Evidence.** S4a (validly signed lower `security_version`) is rejected with `DOWNGRADE_REJECTED`
and the slot is untouched. S4b (lower `version`, same `security_version`) installs. Invariant I4
checks the floor never decreases.
