# Current implementation plan

## Goal

v1 `backend/syz-guided/` backend is complete, MOCK migration is done, and the
environment-limited live validation pass has been executed. The remaining work is
the live arm64 KVM campaign, which requires a dedicated Linux KVM environment.

## Scope

- Linux arm64 KVM only
- syzkaller-based execution via stock syzkaller
- KASAN/KCOV-backed feedback
- sequential cross-entry candidates with simple hard-order constraints
- candidate-aware crash triage

## v1 backend phases (DONE)

### Phase 0 — discovery and planning
- [x] Read all context, agents, plans, skills
- [x] Map existing bridge codepaths
- [x] Identify producer/consumer boundaries
- [x] Document exact candidate.json and witness_plan.json schemas
- [x] Write implementation plan
- [x] Write schema-impact analysis

### Phase 1 — schemas and fixtures
- [x] Create backend/syz-guided/ directory structure
- [x] Write JSON schemas: state_model_v1, target_profile, relation_graph_v1, triage_report_v1
- [x] Create test fixtures from real bridge artifacts
- [x] Add schema validation helpers

### Phase 2 — state model builder and seed synthesis
- [x] build_state_model.py: candidate.json + witness_plan.json → state_model_v1.json
- [x] validate_state_model.py: validate against schema
- [x] synthesize_seeds.py: state_model → .prog seeds
- [x] emit_seed_manifest.py: produce seed manifest
- [x] test_state_model.py (24 tests), test_seedgen.py (9 tests)

### Phase 3 — orchestrator and scoring
- [x] score.py: multi-dimensional scoring
- [x] queue.py: hot/cold queues with promotion/demotion
- [x] campaign.py: bounded campaign orchestrator
- [x] prefix_safe_mutator.py, relation_guard.py
- [x] syzkaller_runner.py

### Phase 4 — triage and repro
- [x] parse_kasan.py: KASAN report parser
- [x] match_candidate.py: crash → candidate matching
- [x] report.py: triage_report_v1.json emitter
- [x] candidate_repro.py: prefix-preserving repro wrapper

### Phase 5 — narrow validation
- [x] smoke_seedgen.sh (PASS)
- [x] smoke_campaign.sh (PASS — 10 iterations, best score 0.591)
- [x] smoke_triage.sh (PASS — verdict: plausible, score 1.00)
- [x] 54 unit tests pass
- [x] Validation evidence recorded in plans/validation-report.md

## Migration phase (DONE)

- [x] Remove mock/ directory
- [x] Create plans/mock-removal-audit.md
- [x] Create plans/syzkaller-runtime-proof.md
- [x] Update README.md (removed MOCK steps/sections)
- [x] Update context/current-status.md (removed false "mock intact" claim)
- [x] Update context/known-issues.md (updated risks)
- [x] Update plans/repo-map.md (removed dead mock section)
- [x] Update CLAUDE.md (removed mock-handoff-maintainer skill)
- [x] Update plans/validation-report.md (added re-run evidence)

## Live validation pass (DONE — environment-limited)

- [x] Identified host as macOS 26.3.1 (Darwin arm64) — no Linux KVM
- [x] Built syz-manager (linux/arm64, 72M ELF) from in-repo syzkaller/ source
- [x] Built syz-manager (darwin/arm64, 76M) from in-repo syzkaller/ source
- [x] Built syz-execprog (linux/arm64, 52M ELF) from in-repo syzkaller/ source
- [x] Confirmed syzkaller/ is clean upstream at aeea1c723 (no patches needed to build)
- [x] Confirmed overlay image backing file is missing (/home/charles/kvm-fuzz/images/arm64.img)
- [x] Regenerated state_model_v1.json, target_profile.json, relation_graph_v1.json for fixture
- [x] Synthesized 4 seeds, all with correct bootstrap prefix in prog text
- [x] Generated syz-manager config via backend generate_syz_config()
- [x] Confirmed no SYZ_DIR fallback to system PATH
- [x] Confirmed naming boundary: seeds use $kvm (syzkaller format), state model uses $KVM (internal)
- [x] Campaign smoke re-run: 10 iterations, best=0.591 PASS
- [x] Triage smoke re-run: verdict=plausible, score=1.00 PASS
- [x] Updated validation-report.md with exact evidence

## Next: vm_validator — disposable QEMU TCG validator on Mac

See `plans/vm-validator-phase0.md` for the full Phase 0 design.

Goal: run one `.prog` inside a real arm64 Linux kernel under QEMU TCG on macOS,
collect dmesg/crash output, feed it to the existing triage pipeline. No syz-manager,
no long campaign, no mutation. One-shot: boot → inject → run → capture → triage → exit.

### Phase 0 — discovery and design (DONE)
- [x] Read all backend implementation entrypoints
- [x] Map artifact inputs: candidate.json, witness_plan.json (read-only from bridge)
- [x] Map runtime inputs: state_model_v1.json, target_profile.json, seed_*.prog
- [x] Map operator-provided inputs: kernel Image, disk image, SSH key, syz-execprog
- [x] Verified triage integration point: `build_triage_report(crash_text, tp, sm, calls)`
- [x] Verified seed format: text `.prog` from synthesize_seeds.py
- [x] Confirmed schema impact: none — pure consumer, no new schemas
- [x] Confirmed no changes to bridge artifacts or existing backend modules
- [x] Identified environment blockers vs code gaps
- [x] Identified risk: syz-execprog text vs binary prog format (needs verification)
- [x] Identified risk: guest /dev/kvm depends on CONFIG_KVM=y in guest kernel
- [x] Identified risk: no standalone arm64 disk image exists yet
- [x] Wrote plans/vm-validator-phase0.md
- [x] Updated plans/current.md, plans/repo-map.md, plans/schema-impact.md

### Phase 1 — implement vm_validator modules, tests, smoke (DONE)
- [x] `vm_validator/__init__.py` — package marker
- [x] `vm_validator/preflight.py` — check QEMU, kernel, disk, syz-execprog, SSH key (82 lines)
- [x] `vm_validator/vm_runner.py` — boot QEMU TCG, SSH wait, shutdown (167 lines)
- [x] `vm_validator/prog_injector.py` — scp + ssh execute syz-execprog (130 lines)
- [x] `vm_validator/log_collector.py` — pull dmesg, extract KASAN section (96 lines)
- [x] `vm_validator/run_one.py` — top-level orchestrator with triage hook (186 lines)
- [x] `scripts/smoke_vm_validator.sh` — preflight-only smoke (PASS)
- [x] `tests/test_vm_validator.py` — 30 unit tests (PASS)
- [x] All 24 existing state_model tests still pass
- [x] Updated plans/current.md, plans/validation-report.md

### Phase 2 — environment prerequisites (DONE)
- [x] Create standalone arm64 rootfs (arm64-standalone.qcow2, 11.5 GiB)
- [x] Fix fstab (removed stale BOOT/UEFI entries, root → /dev/vda1)
- [x] Verify guest kernel has CONFIG_KVM=y (yes, but /dev/kvm absent under TCG)
- [x] Verify syz-execprog accepts text `.prog` format (confirmed: parses directly)
- [x] Build syz-execprog via Makefile with syscall descriptions (46M, linux/arm64)
- [x] Build syz-executor inside guest from source (4.1M, linux/arm64)
- [x] Full boot smoke: QEMU TCG → systemd → SSH ready in ~5 min

### Phase 3 — live validation (DONE — TCG-limited)
- [x] Full boot with VM_KERNEL, VM_DISK, VM_SSH_KEY
- [x] SCP syz-execprog + syz-executor + seed into guest
- [x] syz-execprog executed seed_full_run.prog (connected to executor, syscalls ran)
- [x] KVM ioctls returned EINVAL (no /dev/kvm under TCG — expected)
- [x] Collected 348-line dmesg, no KASAN crash (correct for EINVAL path)
- [x] Triage pipeline: verdict=insufficient_data, score=0.0 (correct)
- [x] Updated validation-report.md with full live execution evidence

### What remains for full syz-manager campaign

Required on a Linux arm64 KVM host (or after vm_validator proves the baseline):

1. Build syz-executor via CGO cross-compiler.
2. Provide standalone disk image compatible with syz-manager QEMU mode.
3. Set `SYZ_DIR`, run bounded campaign, triage results.
4. Update validation-report.md.

## Done criteria (met for software validation)

- [x] backend/syz-guided/ exists with all v1 modules
- [x] Schemas validate
- [x] State model generation is deterministic for the KVM fixture
- [x] Seeds parse and preserve prefix constraints
- [x] Triage emits structured reports matching focus frames
- [x] Validation evidence recorded
- [x] MOCK removed; syzkaller is canonical runtime
- [x] Syzkaller runtime proof documented
- [x] syzkaller builds successfully from in-repo source
- [x] vm_validator one-shot execution on macOS (DONE — TCG-limited, no /dev/kvm)
- [ ] Live arm64 KVM campaign (blocked: requires Linux KVM host)
