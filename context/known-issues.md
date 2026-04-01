# Known issues

## Current risks

- **KVM device required for meaningful UAF trigger**: `/dev/kvm` is absent under
  QEMU TCG. KVM ioctls return EINVAL, so no kernel KVM codepaths are exercised.
  A real Linux KVM host (or nested-virt-capable hypervisor) is needed to trigger
  actual KVM UAF candidates.
- **Overlay image requires base** (resolved for new work): `arm64-standalone.qcow2`
  (11.5 GiB) is the bootable image. The old `arm64-isolated-overlay.qcow2` still
  references a missing base and should not be used.
- **syz-executor built inside guest**: The executor was compiled from source inside
  the QEMU guest (native g++). For a portable workflow, a cross-compiler on the
  host or a pre-built binary should be used.
- **syzkaller integration may need light patching**: Seed control and candidate
  metadata export may require minor syzkaller modifications for a real campaign.
- **Candidate-aware repro may accidentally minimize away required prefix state**.
- **Bridge/runtime contracts may drift if not documented explicitly**.
- **Naming boundary in seeds vs state model**: Seeds use syzkaller prog format
  (`openat$kvm`, lowercase) while state model stores internal names (`openat$KVM`,
  uppercase). Relation guard operates on internal names. Not a bug, but a boundary
  that needs attention if a prog-parser integration is added.
- `scripts/e2e_witness_smoke.sh` and `scripts/e2e_harness_smoke.sh` contain dead
  `MOCK_ROOT` variable references; cosmetic issue, scripts stop before reaching those
  branches.

## v1 constraints

- Keep scope narrow.
- Keep most logic in user space.
- Avoid deep syzkaller forking.
- Avoid broad abstractions without concrete payoff.

## Mock vs backend syzkaller distinction

The deleted `mock/` path used a **patched** syzkaller (commit `169724fe...`) with
IVSHM + unix socket + JSON-export patches for Healer corpus sharing and ML model
training. The new `backend/syz-guided/` uses **stock upstream syzkaller** (no patches
needed). The Trash preserves the old patched build as evidence.
See `plans/syzkaller-runtime-proof.md` for the full comparison.

## Migration notes

- `mock/` directory removed; all downstream references in docs/plans/CLAUDE.md updated.
- Bridge still produces `mock_seed.json` as an artifact — this is a bridge output, not a
  runtime path. Schema is preserved.
- `skills/mock-handoff-maintainer/SKILL.md` kept as archive; removed from CLAUDE.md active
  skill list.
