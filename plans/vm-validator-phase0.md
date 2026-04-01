# vm_validator — Phase 0 design

## What this is

A disposable QEMU TCG VM runner that executes one synthesized `.prog` inside a
real arm64 Linux kernel on macOS, collects dmesg/crash output, feeds it to the
existing candidate-aware triage, and shuts down. No syz-manager, no long-lived
campaign, no corpus mutation. One-shot: boot → inject → run → capture → triage → exit.

## Why

The gap between "smoke tests pass" and "real kernel execution" is currently blocked
by the requirement for a full Linux KVM host. A QEMU TCG VM running on the Mac
closes that gap at the cost of speed (~10-20x slower, acceptable for a single
bounded execution).

## Architecture

```
                    existing backend
                    ─────────────────────────────────────
candidate.json ──┐
                 ├→ build_state_model.py → state_model_v1.json
witness_plan.json┘                        │
                                          ├→ target_profile.json
                                          └→ synthesize_seeds.py → seed_full_run.prog
                                                                     │
                    vm_validator (NEW)                                │
                    ─────────────────────────────────────             │
                                                                     ▼
                    preflight.py ── check kernel, image, qemu
                         │
                    vm_runner.py ── boot QEMU TCG, wait for SSH
                         │
                    prog_injector.py ── scp .prog + syz-execprog → VM
                         │                run syz-execprog inside guest
                         │                capture stdout/stderr/dmesg
                         │
                    log_collector.py ── pull dmesg, extract KASAN
                         │
                    ┌────┘
                    ▼
                    existing triage
                    ─────────────────────────────────────
                    parse_kasan.py → match_candidate.py → report.py
                         │
                         ▼
                    triage_report_v1.json
```

## What is reused vs new

### Reused (no changes)

| Module | Role | Interface |
|--------|------|-----------|
| `state_model/build_state_model.py` | Artifact generation | CLI: `--candidate --witness-plan --out-dir` |
| `seedgen/synthesize_seeds.py` | Seed synthesis | CLI: `--state-model --out-dir` |
| `triage/parse_kasan.py` | KASAN parsing | `parse_kasan_report(text) → dict\|None` |
| `triage/match_candidate.py` | Crash→candidate match | `match_crash(parsed, target_profile) → dict` |
| `triage/report.py` | Report emission | `build_triage_report(crash_text, tp, sm, calls) → dict` |
| `schemas/` | Validation | All four schemas unchanged |

### New (to create)

| File | Role | Size estimate |
|------|------|---------------|
| `vm_validator/__init__.py` | Package marker | trivial |
| `vm_validator/preflight.py` | Check QEMU, kernel, image, syz-execprog, SSH key | ~80 lines |
| `vm_validator/vm_runner.py` | Boot QEMU TCG, wait for SSH ready, shutdown | ~120 lines |
| `vm_validator/prog_injector.py` | Copy .prog + syz-execprog to VM, execute, capture output | ~80 lines |
| `vm_validator/log_collector.py` | Pull dmesg from guest, extract crash section | ~60 lines |
| `vm_validator/run_one.py` | Top-level orchestrator: preflight → boot → inject → collect → triage | ~100 lines |
| `scripts/smoke_vm_validator.sh` | End-to-end smoke using fixture candidate | ~40 lines |
| `tests/test_vm_validator.py` | Unit tests for parseable outputs (no VM needed) | ~60 lines |

Total new code: ~540 lines.

## Artifact inputs

Consumed read-only — no changes to any of these:

| Artifact | Source | Schema |
|----------|--------|--------|
| `candidate.json` | bridge | candidate/v1 |
| `witness_plan.json` | bridge | witness_plan/v1 |
| `state_model_v1.json` | build_state_model.py | state_model/v1 |
| `target_profile.json` | build_state_model.py | target_profile/v1 |
| `seed_*.prog` | synthesize_seeds.py | syzkaller prog format |

## Runtime inputs (operator-provided)

| Asset | Source | Note |
|-------|--------|------|
| arm64 kernel Image | `syzkaller-runtime-export/Image` or custom | Must have KASAN+KCOV |
| arm64 root disk | Must create standalone (see blockers) | Not the overlay — need raw qcow2 or raw img |
| SSH key | `syzkaller-runtime-export/id_rsa` or custom | For guest access |
| syz-execprog binary | Built from `syzkaller/` for linux/arm64 | Runs .prog inside guest |

## Runtime outputs

| Artifact | Producer | Schema |
|----------|----------|--------|
| `vm_run_log.json` | run_one.py | NEW — internal, minimal |
| `guest_dmesg.txt` | log_collector.py | raw text |
| `crash_log.txt` | log_collector.py | KASAN excerpt if found |
| `triage_report_v1.json` | existing report.py | triage_report/v1 (unchanged) |

### vm_run_log.json (new, internal)

No schema needed — strictly internal. Contains:
```json
{
  "candidate_id": "...",
  "seed_used": "seed_full_run.prog",
  "vm_boot_ok": true,
  "prog_executed": true,
  "kasan_detected": false,
  "triage_verdict": "insufficient_data",
  "duration_seconds": 42.5,
  "exit_reason": "clean_shutdown"
}
```

## Schema impact

**None.** This subsystem is a pure consumer of existing artifacts and a user of the
existing triage interface. It does not modify or extend any schema. `vm_run_log.json`
is internal and disposable.

## QEMU TCG execution model

```bash
qemu-system-aarch64 \
  -machine virt -cpu cortex-a57 \
  -m 2048 -nographic \
  -kernel /path/to/Image \
  -drive if=virtio,file=/path/to/disk.qcow2 \
  -append "root=/dev/vda console=ttyAMA0 kasan.fault=panic" \
  -net user,hostfwd=tcp::10022-:22 -net nic \
  -no-reboot
```

Key points:
- **TCG mode** (no `-enable-kvm`): software emulation, works on macOS
- **`-no-reboot`**: QEMU exits on kernel panic (KASAN fault → panic → exit)
- **Port forward**: SSH on localhost:10022 for file injection
- **Guest `/dev/kvm`**: Guest kernel may or may not have KVM depending on build config.
  The `.prog` exercises KVM ioctls which require `/dev/kvm` inside the guest. This
  requires the guest kernel to be built with `CONFIG_KVM=y`. The existing Image likely
  has this.

## Exact execution sequence

1. **preflight**: verify QEMU binary, kernel image, disk image, syz-execprog, SSH key
2. **boot**: start QEMU TCG, wait for SSH port to accept connections (poll with timeout)
3. **inject**: `scp` the `.prog` file and `syz-execprog` binary into the guest
4. **execute**: `ssh root@localhost -p 10022 ./syz-execprog -repeat=1 ./seed.prog`
5. **collect**: `ssh root@localhost -p 10022 dmesg` → extract KASAN section if present
6. **triage**: call `build_triage_report(crash_text, target_profile, state_model)`
7. **shutdown**: `ssh root@localhost -p 10022 poweroff` or kill QEMU
8. **emit**: write `vm_run_log.json` + `triage_report_v1.json`

## Blockers — environment vs code

### Environment blockers (not code gaps)

| Blocker | Severity | Resolution |
|---------|----------|------------|
| No standalone arm64 disk image | HIGH | Must create one: `debootstrap` a minimal arm64 rootfs, or find/build a syzkaller `create-image.sh` output. The overlay in runtime-export requires a base image that isn't present. |
| syz-execprog for linux/arm64 | MEDIUM | Already built to `/tmp/syz-execprog-linux-arm64` (52M ELF). Needs to be in a stable path. |
| Guest `/dev/kvm` | MEDIUM | Guest kernel must have `CONFIG_KVM=y`. If the preserved Image has it, the KVM ioctls will work even under TCG. If not, `openat(/dev/kvm)` fails and the entire prog is a no-op. Testable at boot. |
| TCG speed | LOW | ~10-20x slower than KVM. For one-shot execution this is seconds→minutes. Acceptable. |

### Code gaps (what vm_validator must implement)

| Gap | Complexity | Notes |
|-----|-----------|-------|
| QEMU lifecycle management | Medium | Start, wait-for-SSH, shutdown, cleanup. Subprocess + SSH polling. |
| syz-execprog injection | Low | scp two files, run one command over SSH. |
| dmesg collection | Low | SSH command, text extraction. |
| Triage integration | Trivial | Direct function call to existing `build_triage_report()`. |
| Preflight checks | Low | File existence + binary format checks. |

## File layout

```
backend/syz-guided/
  vm_validator/
    __init__.py
    preflight.py         # check all prerequisites
    vm_runner.py         # QEMU TCG lifecycle (boot, ssh-wait, shutdown)
    prog_injector.py     # scp + ssh execute syz-execprog
    log_collector.py     # pull dmesg, extract crash
    run_one.py           # top-level: preflight → boot → inject → collect → triage
  scripts/
    smoke_vm_validator.sh  # NEW
  tests/
    test_vm_validator.py   # NEW
```

## Risks

1. **Guest /dev/kvm may not exist**: If the preserved kernel was built without
   `CONFIG_KVM=y`, all KVM ioctls fail harmlessly. The prog executes but no UAF
   path is reached. This is detectable and would degrade to "proof of pipeline
   execution" without "proof of candidate reachability."

2. **No standalone disk image exists yet**: The overlay in `syzkaller-runtime-export/`
   cannot be used without its base. Creating a minimal arm64 rootfs is a separate
   prerequisite task. syzkaller's `tools/create-image.sh` can do this.

3. **syz-execprog may not load `.prog` format directly**: syz-execprog expects a
   serialized binary prog, not the text format. May need `syz-prog2c` or a text→binary
   conversion step. This needs verification against the syzkaller codebase.

4. **SSH key format**: The preserved `id_rsa` must match what's authorized in the
   guest's `authorized_keys`. If the disk image is newly created, the key must be
   injected.

## What this does NOT do

- No mutation, no corpus evolution, no long campaign
- No syz-manager — bypasses it entirely
- No coverage collection beyond KASAN detection
- No new schemas or schema changes
- No changes to bridge artifacts
- Does not broaden support claims beyond arm64 KVM
