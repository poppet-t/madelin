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
- 84 unit tests pass across all modules (including 30 vm_validator tests).
- 4 smoke scripts pass (seedgen, campaign, triage, vm_validator).
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

## What is now true after Linux KVM preparation

- `plans/linux-kvm-runbook.md` provides the concrete execution plan for Linux KVM hosts.
- Three reusable Linux-side helper scripts exist (validated on macOS, ready for Linux):
  - `check_linux_kvm_host.sh` — host readiness preflight (PASS/WARN/FAIL summary)
  - `run_linux_kvm_one_shot.sh` — one-shot seed execution under QEMU/KVM
  - `run_linux_syz_manager.sh` — bounded syz-manager campaign launcher with timeout
- All three scripts fail honestly on macOS (report "not Linux" and exit nonzero).
- `vm_validator/` module (5 Python files, 30 unit tests) is fully implemented.

## What remains for full v1 readiness

- Real KVM-triggered KASAN crash requires a Linux arm64 KVM host with `/dev/kvm`.
- One-shot seed execution under QEMU/KVM (using `run_linux_kvm_one_shot.sh`).
- Bounded syz-manager campaign (using `run_linux_syz_manager.sh`).
- Candidate-aware triage on real crash output.
- Repro wrapper end-to-end validation on real crash input.
- Coverage signal integration from syzkaller.
- See `plans/linux-kvm-runbook.md` for the full step-by-step guide.

## Migration status

- mock/ removed; all relevant doc/plan references updated.
- `plans/mock-removal-audit.md` classifies every remaining MOCK reference.
- `plans/syzkaller-runtime-proof.md` documents the syzkaller runtime selection path.
- `plans/validation-report.md` records full evidence for both smoke-level and
  environment-audit validation passes.
