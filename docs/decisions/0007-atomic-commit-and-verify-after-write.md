# 0007: Atomic commit and verify-after-write

**Decision.** `state.json` is the only commit point: write a temp file, `fsync`, `os.replace`, then
`fsync` the directory. After writing the inactive slot, read it back and re-hash it before
switching to it. Leftover temp files are discarded at start, never trusted.

**Why.** A torn slot write must never be promoted, and a torn state write must never be read.

**Limit.** `os._exit` proves write ordering and the commit point, not durability against real power
loss (see `docs/LIMITATIONS.md`).

**Evidence.** S8 P1 to P5 and P9 (crash with a temp file on disk), the atomicity unit tests, and
invariant I2 (state parses after every crash, no temp files left after restart).
