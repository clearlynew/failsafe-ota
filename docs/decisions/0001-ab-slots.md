# 0001: A/B slots instead of in-place update

**Decision.** Keep two slots. Write the new image only to the inactive slot, then switch with one
atomic pointer write (`state.json`).

**Why.** An in-place update leaves no good image if power fails mid-write. With two slots the
running image is never touched during an update.

**Cost.** Double the storage.

**Evidence.** S8 P1 to P5 (power cut during download, slot write and flip) all leave a runnable
device; invariant I1 checks the active slot's hash matches `state.json` after every scenario.
S2a, S2b and S3a also assert the inactive slot was never written when a release is rejected.
