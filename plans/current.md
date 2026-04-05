# Current implementation plan

## Goal

Pivot Madelin from a narrow arm64-KVM-only validation slice into an artifact-driven,
hardware-light arm64 kernel validation workflow centered on **target packs** while
preserving the static-to-dynamic contract:

`uafx -> bridge export/import -> candidate.json -> witness_plan.json -> backend/syz-guided -> triage_report_v1.json`

## Active scope

- Linux arm64 target packs: `kvm`, `io_uring`, `net`, `bpf`, `fs`
- UAFX-first producer flow: raw warning -> bridge export -> normalized candidate
- Deterministic witness planning and explicit unsupported cases
- Hardware-light dry-run validation on ordinary VM-capable environments
- Legacy KVM support preserved as the initial pack

## Completed phases

### Phase 0 — context engineering and repo orchestration
- [x] Update planning artifacts around the producer-first target-pack pivot
- [x] Use repo-local orchestration guidance (`AGENTS.md`, `CLAUDE.md`, `docs/ai/*`, `context/*`)
- [x] Preserve schema-impact tracking before code changes

### Phase 1 — UAFX-first target metadata generation
- [x] Generalize `uafx_fork/tools/export_bridge_candidate.py`
- [x] Export additive target metadata: `kernel_area`, `subsystem`, `target_family`, `entry_kind_hint`
- [x] Add raw-warning fixtures for `io_uring`, `net`, `bpf`, `fs`
- [x] Generate bridge-export fixtures for `io_uring`, `net`, `bpf`, `fs`
- [x] Stop hardcoding `kvm` in the bridge importer

### Phase 2 — target-pack bridge generalization
- [x] Add static pack registry under `targets/{kvm,io_uring,net,bpf,fs}`
- [x] Extend normalized entry kinds for software-reachable packs
- [x] Make entry classification and syscall template generation pack-aware
- [x] Generalize witness planning around pack lifecycle edges
- [x] Add generic witness emission/validation for non-KVM packs
- [x] Add generic harness generation for non-KVM packs
- [x] Preserve KVM-specific witness/harness behavior

### Phase 3 — backend pack generalization
- [x] Make state-model build pack-aware from manifests
- [x] Make seed synthesis pack-aware from manifests
- [x] Keep campaign + triage contracts unchanged
- [x] Regenerate backend pack fixtures from bridge-produced artifacts
- [x] Add backend dry-run proofs that extend through campaign summary and triage report

### Phase 4 — docs, operator flow, and AI scaffolding
- [x] Rewrite public scope docs around hardware-light arm64 target packs
- [x] Update AI/operator docs for safe target-pack extension
- [x] Add new skills for target-pack design, witness-plan discipline, fixture generation, smoke authoring, triage extension
- [x] Replace stale root `mock/`-based smokes with local pack-aware smokes

### Phase 5 — validation
- [x] Full `uaf-bridge` pytest suite passes (`76` tests)
- [x] Full `backend/syz-guided` unittest suite passes (`88` tests)
- [x] Existing backend smokes pass (`smoke_seedgen`, `smoke_campaign`, `smoke_triage`, `smoke_vm_validator`)
- [x] `backend/syz-guided/scripts/smoke_pack.sh --pack {kvm,io_uring,net,bpf,fs}` passes
- [x] `scripts/e2e_target_pack_smoke.sh --pack {kvm,io_uring,net,bpf,fs}` passes
- [x] Validation evidence recorded in `plans/validation-report.md`

### Phase 6 — io_uring real-runtime validation lane

**Goal**: Make `io_uring` the first non-KVM pack with a credible real-runtime validation
path, evidence artifacts, and subsystem-aware triage — runnable on ordinary arm64 Linux VMs.

**Audit findings** (2026-04-02):
- Runtime lane exists: `backend/syz-guided/runtime/io_uring_lane.py` (385 lines)
- Verdict classifier exists: `backend/syz-guided/triage/io_uring_verdict.py` (6 classes)
- Campaign shell script exists: `backend/syz-guided/scripts/run_io_uring_vm_campaign.sh` (8-step pipeline)
- Evidence artifacts already emitted: execution_trace_summary, preserved_prefix_report,
  edge_coverage_summary, concurrency_window_report, candidate_alignment_report, runtime_verdict
- Existing tests: 2 lane tests, 3 verdict tests, 1 pack fixture dry-run
- Gap: triage is generic (no io_uring symbol tables beyond candidate focus frames)
- Gap: only 3 of 6 verdict classes tested
- Gap: no documented end-to-end proof
- Gap: manifest maturity still "scaffolded"
- Gap: AI scaffolding not updated for runtime lane

**Steps**:
- [x] Audit all io_uring components across the repo
- [x] Add `triage/io_uring_symbols.py` — subsystem-specific symbol tables for enhanced matching
- [x] Add comprehensive tests: all 6 verdict classes, prefix preservation, symbol-enriched triage
- [x] Update manifest maturity and add `enable_syscalls` for syz-manager config generation
- [x] Create `plans/io_uring-runtime-proof.md` — documented dry-run proof of full artifact chain
- [x] Update AI scaffolding: context/, AGENTS.md, skills, docs/ai/OPENCLAW-RUNBOOK.md
- [x] Run all tests/smokes and record validation evidence (121 tests pass, all smokes pass)

**Constraints**:
- No schema version changes
- No KVM regressions
- Keep the smallest safe diff
- Do not claim live execution validation without evidence

### Phase 7 — net (nf_tables) live-validation lane hardening

**Goal**: Force the arm64 QEMU nf_tables path across the line into a usable live lane with
strict preflight, staged execution, layered verdicting, repro artifacts, and known-bug hygiene.

**Completed in this pass**:
- [x] Replace the old host-style net runtime lane with a guest-backed arm64 QEMU path
- [x] Make `run_net_vm_campaign.sh` require kernel, disk image, and SSH key inputs
- [x] Enforce strict live preflight before any seed execution
- [x] Stage execution as single-seed -> four-seed -> short bounded campaign -> optional extended
- [x] Emit timestamped `out/net-runtime/live-YYYYMMDD-HHMMSS/` artifact trees
- [x] Split verdicting into execution / crash / candidate evidence layers
- [x] Add crash repro reruns, reproducibility classification, and minimization handoff artifacts
- [x] Add manual known-bug review artifacts and duplicate-hygiene gating before novelty claims
- [x] Add targeted tests for helpers, verdicts, repro behavior, layout, and failure classes
- [x] Update operator and AI scaffolding to match the live path

**Follow-on guest-enablement work completed after hardening**:
- [x] Diagnose the old SSH banner timeout as a guest-readiness problem rather than a key problem
- [x] Add banner-and-command-based readiness detection instead of raw TCP-port readiness
- [x] Make guest-resident `syz-execprog` and `syz-executor` usable in the lane
- [x] Add `stage_arm64_guest_tooling.sh` to export validated linux/arm64 guest binaries back to the host
- [x] Create and use `syzkaller-runtime-export/arm64-live-ready.qcow2` with `init=/root/madelin-guest-init.sh`
- [x] Reach real guest-side seed execution start under the replacement image

**Current blocker after guest readiness**:
- [ ] Tune or classify the first bounded guest-side seed run, which can exceed the current per-seed timeout under TCG

### Phase 8 — lab-only net bug lab scaffolding

**Goal**: Keep the existing `net` runtime lane strict, but expose it as a reproducible **lab-only**
workflow for synthetic or already-disclosed net bugs with deterministic artifacts, exact blocker
reports, and bounded AI-assisted ranking inputs.

**Implementation constraints**:
- [ ] Preserve the artifact boundary: `warning -> candidate.json -> witness_plan.json -> backend artifacts -> runtime -> triage`
- [ ] Keep runtime proof gated on real execution evidence only
- [ ] Keep AI ranking/triage advisory only; never let it count as proof
- [ ] Add only additive artifacts and helper scripts; do not widen support claims
- [ ] Reuse the current `net` runtime lane and proof-mode kernel flow instead of introducing a new framework

**Planned work**:
- [ ] Add a first-class lab run bundle with kernel provenance, source-frame summary, and blocker reports
- [ ] Add a lab overlay classifier that maps existing verdicts into lab-only states without changing the existing verdict schema
- [ ] Add deterministic local ranking helpers for net files and seeds plus ranking decision artifacts
- [ ] Add a dedicated lab-only synthetic net bug target description under `targets/net/`
- [ ] Make minimized-seed handoff and exact source-frame evidence first-class lab artifacts
- [ ] Update docs/status/validation notes to keep the support boundary explicit

**Will not claim after this phase**:
- [ ] No broader net subsystem support than the validated lab pack and current staged live lane
- [ ] No real-world novelty, exploitability, or CVE implication
- [ ] No proof beyond synthetic/disclosed lab targets with saved runtime evidence


## Remaining gaps

- Real KVM-triggered crash validation still requires a Linux arm64 KVM host.
- `fs` currently validates the mount-API family end to end; FUSE remains scaffolded, not separately proven.
- `ublk` is still the recommended next pack and has not been implemented.
- Generic witness/harness generation is intentionally contract-first and does not claim semantic argument synthesis beyond the emitted fixtures.
- `io_uring` real-runtime lane is implemented and dry-run proven; live execution on a real arm64 Linux VM remains the next validation step.
- `net` (nf_tables) live lane is implemented and strict-preflight-gated; remaining work is environment-backed execution evidence on a prepared arm64 guest image.
