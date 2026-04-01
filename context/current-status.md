# Current status

## Current truth

- The repo is organized as an artifact-centered pipeline.
- UAFX and bridge stages exist and must remain the canonical static producers.
- `backend/syz-guided/` is the canonical v1 syzkaller-based runtime backend.
- v1 is intentionally narrow and focused on Linux arm64 KVM.
- Candidate-aware triage and reproducible artifacts are mandatory backend properties.
- Bridge artifacts (candidate.json, witness_plan.json) are consumed read-only by the backend.
- All backend schemas validate against their JSON Schema definitions.
- The legacy `mock/` directory has been removed; `backend/syz-guided/` is the only runtime consumer.
- `syzkaller/` contains a clean upstream reference checkout (unmodified, no built binaries).
- `syzkaller-runtime-export/` preserves the arm64 KVM environment from the known working run.

## What is now true after v1 backend work

- `backend/syz-guided/` exists with full directory structure.
- Runtime schemas exist and validate (state_model_v1, target_profile, relation_graph_v1, triage_report_v1).
- State model generation is deterministic for the KVM fixture candidate.
- Seed synthesis emits 4 prefix-preserving .prog seeds for the KVM candidate.
- A bounded orchestrator exists with scoring, queuing, and campaign lifecycle.
- Candidate-aware triage emits structured reports with verdict classification.
- Prefix-safe mutation preserves bootstrap prefix and sticky calls.
- Relation guard validates resource chain integrity post-mutation.
- 54 unit tests pass across all modules.
- 3 smoke scripts pass (seedgen, campaign, triage).
- syz-manager and syz-execprog build successfully from the in-repo syzkaller/ source tree
  (confirmed: `GOOS=linux GOARCH=arm64 go build ./syz-manager/` produces a valid 72M ELF).

## What is now true after vm_validator live execution

- QEMU TCG boots the arm64 kernel (`7.0.0-rc5-gbbeb83d3182a`) on macOS to SSH-ready.
- `arm64-standalone.qcow2` (11.5 GiB) replaces the broken overlay as the bootable image.
- Guest fstab fixed (removed stale BOOT/UEFI entries that caused emergency mode).
- syz-execprog (46M, built via Makefile with syscall descriptions) parses text `.prog` files directly.
- syz-executor (4.1M, compiled inside guest from source) connects to syz-execprog via flatrpc.
- Full execution pipeline proven: seed → syz-execprog → syz-executor → syscalls → dmesg → triage.
- KVM ioctls return EINVAL under TCG (no `/dev/kvm`) — expected, not a code issue.
- Triage pipeline produces correct `insufficient_data` verdict when no crash occurs.

## What remains for full v1 readiness

- Real KVM-triggered KASAN crash requires `/dev/kvm` (Linux KVM host or nested virt):
  - `/dev/kvm` device present
  - `SYZ_DIR` set to the directory containing built binaries
- End-to-end campaign with actual kernel execution (syz-manager loop).
- Repro wrapper end-to-end validation.
- Coverage signal integration from syzkaller.

## Migration status

- mock/ removed; all relevant doc/plan references updated.
- `plans/mock-removal-audit.md` classifies every remaining MOCK reference.
- `plans/syzkaller-runtime-proof.md` documents the syzkaller runtime selection path.
- `plans/validation-report.md` records full evidence for both smoke-level and
  environment-audit validation passes.
