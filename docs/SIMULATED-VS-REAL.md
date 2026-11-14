# What is simulated and what is real

| Component | In this project | Real-world equivalent |
|---|---|---|
| Device | Python process per simulated device | Microcontroller or embedded Linux board |
| A/B slots | Two directories, `slot_a/` and `slot_b/` | Two flash regions or partitions managed by a bootloader |
| "Which slot runs" | `state.json`, updated atomically with `os.replace` | Bootloader state (image trailer flags, boot environment variables) |
| "Boot" | The updater starts the slot's `fw.py` as a subprocess | The bootloader jumps into the selected image |
| Trial and commit | `status=TRIAL`, `trial_attempts_left`, commit writes `STABLE` | Test image plus confirm call (MCUboot) or `bootcount` / `upgrade_available` (U-Boot) |
| Image verification | Done by `updater.py` against a public key file | Done by the bootloader against a key it protects |
| Power cut | `os._exit` at named points | Real power loss, flash erase and write behaviour |
| Cloud side | **Real:** IoT Core, Jobs, Shadow, S3, KMS, IAM, Terraform | Same |

## What this README says, and does not say
| Says | Does not say |
|---|---|
| Update protocol and failure handling, tested against a simulated A/B device | Implemented a bootloader |
| Python A/B slot simulator | Real A/B firmware partitions, or secure boot |
| Atomic commit point via write, fsync, rename | Power-loss safe on real flash |
| Signed manifest verified before install, with downgrade protection | Hardware-rooted trust |
| Fault injection at named crash points | Tested on real hardware |

## What the simulation does not model
- Flash semantics (erase blocks, write granularity, wear, partial page writes).
- Loss of un-fsynced data on real power loss.
- A local attacker who can edit `state.json` or the public key file; a real device protects these
  in the bootloader, ROM or a secure element.
- Watchdogs, boot ROM, and the secure boot chain.

## Porting path to a real bootloader (conceptual, not implemented)
Verify details against the current MCUboot and U-Boot documentation before quoting specifics.

| This project | MCUboot (microcontrollers) | U-Boot A/B (embedded Linux) |
|---|---|---|
| `slot_a/`, `slot_b/` | Primary and secondary image slots, or two XIP slots | Two kernel/rootfs partitions |
| `state.json` active slot and status | Swap state in the image trailer | U-Boot environment variables |
| `TRIAL` with one attempt | "Test" swap: runs once, reverts if not confirmed | `bootcount` / `bootlimit` with `upgrade_available=1` |
| Commit | Application marks the image confirmed | Userspace clears `upgrade_available` |
| Rollback on unconfirmed | Bootloader reverts on the next reset | `altbootcmd` switches partition |
| Signed manifest, checked by `updater.py` | Signature in the image, checked by the bootloader | FIT image signatures / verified boot |
| `security_version` | Security counter for rollback protection | Platform-specific rollback index |

Steps: replace slot directories with partitions and `state.json` logic with bootloader calls; move
verification into the bootloader; change `publish.py` to call the bootloader's image tool; keep the
cloud side unchanged; re-run the scenario catalog with power cuts at flash write boundaries.
