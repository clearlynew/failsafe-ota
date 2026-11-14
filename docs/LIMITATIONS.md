# Known limitations

These are things the project does **not** prove. Read them before relying on any result.

1. **Durability is not proven.** `os._exit` skips Python cleanup but the operating system still
   flushes its page cache, so these tests show write *ordering* and the commit point, not survival
   of a real power cut. A real test needs hardware or a file layer that drops un-fsynced writes.
2. **The device is a simulation.** "Firmware" is a Python script; its self-test is a line it prints.
   Nothing here models flash, a boot ROM, a watchdog or secure boot (see `SIMULATED-VS-REAL.md`).
3. **The device trusts its own files.** A local attacker who can edit `state.json` or the public key
   file defeats the protections. Real devices guard those in the bootloader or a secure element.
4. **Network faults on AWS are injected inside the device's transport.** The S6 scenarios run against
   real AWS, but the outage itself is simulated in the client, not real packet loss.
5. **The "fleet" is 20 processes on one machine.** S9 uses real IoT Jobs, rollout and abort, but the
   devices share one computer and one network connection.
6. **Scale and timing.** Health windows and timeouts are short so the suite runs in minutes; real
   deployments need longer values. S7b relies on AWS's own job-timeout checking (minimum timeout one minute), so it is slow.
7. **One region, local Terraform state.** State is not remote or locked, and it holds resource ARNs,
   so it must never be committed (`.gitignore` excludes it).
8. **CI runs the local tests and Terraform checks only.** The real-AWS scenarios are opt-in
   (`FAILSAFE_E2E=1`) because they need credentials and cost a little.
9. **Single trial attempt.** A power cut during an otherwise good update causes a rollback and a
   retry (decision 0006).
10. **Same version, different content.** A device already on a version reports a job for that
    version as already installed without comparing the image hash.
