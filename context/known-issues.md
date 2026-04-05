# Known issues

## Current risks

- **io_uring has a dry-run-proven runtime lane but no live execution yet**: The
  io_uring runtime lane (runtime execution, evidence artifacts, subsystem-aware triage)
  is fully implemented and dry-run proven. Live validation on an arm64 Linux VM is the
  next step. See `plans/io_uring-runtime-proof.md`.
- **net (nf_tables) live lane now depends on a correctly prepared guest image**: The
  live lane enforces guest-backed preflight and will fail early until the operator supplies
  an arm64 kernel/image/SSH setup with `CONFIG_KASAN=y`, `CONFIG_KCOV=y`, debugfs, and
  nf_tables support. This is now a concrete environment blocker rather than a vague “live
  validation pending” note. See `docs/ai/OPENCLAW-RUNBOOK.md` and `plans/net-runtime-proof.md`.
- **Non-KVM target packs beyond io_uring and net are scaffolded, not proven**: eBPF
  and mount/FUSE packs should be treated as fixture-driven, contract-preserving
  scaffolds until they follow the io_uring/net runtime lane pattern.
- **The original archived full-system guest is not the preferred live path**: `syzkaller-runtime-export/arm64-standalone.qcow2` still boots, but its full Ubuntu systemd bring-up is too slow and brittle under arm64 QEMU TCG for the net live lane. Use `syzkaller-runtime-export/arm64-live-ready.qcow2` with `init=/root/madelin-guest-init.sh` instead.
- **Guest readiness now depends on the minimal init path being present**: if `/root/madelin-guest-init.sh` is missing or the replacement overlay is stale, the live lane can regress to SSH banner timeouts.
- **KVM device required for meaningful UAF trigger**: `/dev/kvm` is absent under
  QEMU TCG. KVM ioctls return EINVAL, so no kernel KVM codepaths are exercised.
  A real Linux KVM host (or nested-virt-capable hypervisor) is needed to trigger
  actual KVM UAF candidates.
- **Overlay image requires base** (resolved for new work): `arm64-standalone.qcow2`
  (11.5 GiB) is the bootable image. The old `arm64-isolated-overlay.qcow2` still
  references a missing base and should not be used.
- **syz-execprog / syz-executor are currently sourced from the guest image**: the preferred net live path uses guest-resident `/root/syz-execprog` and `/root/syz-executor`, with `backend/syz-guided/scripts/stage_arm64_guest_tooling.sh` available to export validated linux/arm64 copies back to the host.
- **syzkaller integration may need light patching**: Seed control and candidate
  metadata export may require minor syzkaller modifications for a real campaign.
- **Candidate-aware repro may accidentally minimize away required prefix state**.
- **Bridge/runtime contracts may drift if not documented explicitly**.
- **Naming boundary in seeds vs state model**: Seeds use syzkaller prog format
  (`openat$kvm`, lowercase) while state model stores internal names (`openat$KVM`,
  uppercase). Relation guard operates on internal names. Not a bug, but a boundary
  that needs attention if a prog-parser integration is added.
- **Linux KVM helper scripts untested on Linux**: `check_linux_kvm_host.sh`,
  `run_linux_kvm_one_shot.sh`, and `run_linux_syz_manager.sh` are validated for
  syntax and macOS-side honest failure only. They have not been executed on a real
  Linux KVM host yet.
- **vm_runner.py hardcodes `-accel tcg`**: The Python `vm_validator/vm_runner.py`
  module uses TCG acceleration. A ~10-line change to accept an `accel` parameter
  is needed to reuse it for KVM. The shell scripts handle this directly.
- `scripts/e2e_witness_smoke.sh` and `scripts/e2e_harness_smoke.sh` contain dead
  `MOCK_ROOT` variable references; cosmetic issue, scripts stop before reaching those
  branches.

## v1 constraints

- Keep scope narrow.
- Keep most logic in user space.
- Avoid deep syzkaller forking.
- Avoid broad abstractions without concrete payoff.

## Legacy patched syzkaller vs stock backend

The deleted `mock/` path used a **patched** syzkaller (commit `169724fe...`) with
IVSHM + unix socket + JSON-export patches for Healer corpus sharing and ML model
training. The new `backend/syz-guided/` uses **stock upstream syzkaller** (no patches
needed). The Trash preserves the old patched build as evidence.
See `plans/syzkaller-runtime-proof.md` for the full comparison.

## Migration notes

- `mock/` directory removed; remaining stale references are tracked in `plans/mock-removal-audit.md`
  and should be treated as cleanup work.
- Bridge still produces `mock_seed.json` as an artifact — this is a bridge output, not a
  runtime path. Schema is preserved.
- `skills/mock-handoff-maintainer/SKILL.md` kept as archive; removed from CLAUDE.md active
  skill list.

- **Current arm64 live kernel still blocks net single-seed execution**: the replacement TCG guest path is now usable and the old SSH/debugfs/cmdline failures were partly false negatives caused by bad remote command transport. After fixing that, strict preflight shows the real blocker: the booted `syzkaller-runtime-export/Image` lacks `CONFIG_NF_TABLES` and does not expose `nf_tables`/`nfnetlink`, so the net live lane still stops before first seed execution. See `out/net-runtime/live-single-seed-operator-3/preflight/preflight_summary.json`.
- **Guest command transport used to misparse multi-word commands over SSH**: this has been fixed in `backend/syz-guided/runtime/net_lane.py`, but any future guest probing should preserve the same quoting discipline or the live lane will regress into false inspection failures.
- **The nftables-enabled kernel now boots, but strict preflight still fails on guest command/tooling checks**: the current repaired overlay path reaches a working early `sshd` under `syzkaller-runtime-export/kernel-export/nftables-enabled-Image`, but the live lane still fails before first seed because:
  - some short non-interactive SSH probe windows are too aggressive under TCG
  - `/root/syz-execprog` and `/root/syz-executor` are not yet validating as usable guest-side tooling in the repaired overlay
  - the `NETLINK_NETFILTER` exposure probe is still failing in strict preflight
  - evidence: `out/net-runtime/live-single-seed-nftables-overlaytest-6/preflight/preflight_summary.json`
- **The new lab-only net scaffolding is not a broad support claim**: the additive lab bundle, lab-state mapping, ranking helpers, and `targets/net/lab/` metadata only support synthetic or already-disclosed lab targets. They do not imply general net subsystem discovery or novelty detection.
- **The current proof-run disk image is not self-contained**: `/tmp/madelin-nft-debug2.qcow2` still depends on a missing backing file at `syzkaller-runtime-export/arm64.img`. When that base image is absent, QEMU exits before guest boot, leaving the net proof lane stuck at `environment/setup failure`. This is now the first blocker for `live-net-proof-with-progress`.
