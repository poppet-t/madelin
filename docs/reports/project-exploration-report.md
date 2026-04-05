# Madelin Project Exploration Report

**Date**: 2026-04-03
**Scope**: Full repository archaeology and systems comprehension
**Method**: Top-down structural inspection, code-level tracing, artifact contract verification

---

## A. Executive Summary

### What Madelin is

Madelin is an artifact-driven Linux kernel vulnerability validation system. It takes statically-discovered cross-entry Use-After-Free (UAF) candidates from UAFX (a custom LLVM-based static analysis tool) and attempts to dynamically confirm them using syzkaller-based execution in arm64 QEMU environments.

### What it currently does

The system implements a three-stage pipeline:

1. **Static analysis** (UAFX) discovers cross-entry UAF candidates in the Linux kernel
2. **Bridge** (`uaf-bridge/`) translates raw UAFX warnings into canonical artifacts (`candidate.json`, `witness_plan.json`)
3. **Runtime backend** (`backend/syz-guided/`) consumes those artifacts, synthesizes syzkaller seeds, orchestrates bounded fuzzing campaigns, and triages crashes against the original candidate

### Current practical maturity

- **Artifact pipeline**: Fully working end-to-end for 5 target packs (KVM, io_uring, net, bpf, fs) in dry-run mode
- **Unit/integration tests**: 76 bridge tests + 88+ backend tests all passing
- **Live execution**: Partially working. macOS QEMU TCG one-shot proven. Linux KVM host execution scaffolded but untested on real hardware. Net lane reached guest-side execution but blocked by guest tooling/timeout issues under TCG
- **Real crash validation**: Not yet achieved. No KASAN crash has been triggered from Madelin seeds on a real kernel

The project is in a **late-prototype / early-validation** stage: the artifact contracts are solid, the dry-run pipeline is deterministic and well-tested, but the system has not yet produced a real dynamic confirmation of a statically-found bug.

---

## B. Repository Map

### Top-level structure

```
madelin/
├── AGENTS.md              # AI agent behavioral guardrails
├── CLAUDE.md              # Claude Code entrypoint (reads, skills, rules)
├── README.md              # Main documentation
├── PRD.md                 # Product requirements document
├── LICENSE                # GNU GPL v2
├── context.md             # Context file index
│
├── context/               # Durable project context (architecture, status, invariants)
│   ├── overview.md
│   ├── architecture.md
│   ├── current-status.md
│   ├── known-issues.md
│   ├── invariants.md
│   └── commands.md
│
├── plans/                 # Implementation plans and validation evidence
│   ├── current.md         # Active plan with phase completion tracking
│   ├── repo-map.md        # Producer/consumer boundary map
│   ├── schema-impact.md   # Contract preservation notes
│   ├── validation-report.md
│   ├── io_uring-runtime-proof.md
│   ├── net-runtime-proof.md
│   ├── linux-kvm-runbook.md
│   ├── mock-removal-audit.md
│   └── syzkaller-runtime-proof.md
│
├── uafx/                  # Static analysis tool (LLVM-based UAF detector)
├── uaf-bridge/            # Bridge: raw warnings → candidate.json → witness_plan.json
├── backend/syz-guided/    # Runtime backend: seeds → campaigns → triage
├── targets/               # Target pack manifests (kvm, io_uring, net, bpf, fs)
├── scripts/               # Root-level E2E smoke scripts
├── tests/                 # Root-level integration tests
├── skills/                # AI skill definitions (16 skills)
├── docs/                  # Additional documentation
│   └── ai/               # AI/operator runbooks
│
├── syzkaller/             # Clean upstream syzkaller checkout (unmodified)
├── syzkaller-runtime-export/  # Preserved arm64 KVM runtime (kernel, disk, SSH keys)
└── out/                   # Generated output artifacts
```

### Important files by role

| File | Role |
|------|------|
| `backend/syz-guided/state_model/build_state_model.py` | Core bridge→backend transformer |
| `backend/syz-guided/seedgen/synthesize_seeds.py` | Seed synthesis from state model |
| `backend/syz-guided/orchestrator/campaign.py` | Bounded campaign orchestrator |
| `backend/syz-guided/triage/report.py` | Triage report generation |
| `backend/syz-guided/triage/match_candidate.py` | Crash-to-candidate matching |
| `backend/syz-guided/triage/parse_kasan.py` | KASAN log parser |
| `backend/syz-guided/mutator/prefix_safe_mutator.py` | Prefix-preserving mutation |
| `backend/syz-guided/mutator/relation_guard.py` | Resource chain integrity validator |
| `backend/syz-guided/pack_registry.py` | Target pack manifest resolution |
| `backend/syz-guided/vm_validator/run_one.py` | One-shot VM execution orchestrator |
| `backend/syz-guided/runtime/io_uring_lane.py` | io_uring real-runtime execution lane |
| `backend/syz-guided/runtime/net_lane.py` | net (nf_tables) real-runtime execution lane |
| `uaf-bridge/uafx_fork/tools/export_bridge_candidate.py` | UAFX warning → bridge export |
| `uaf-bridge/extractor/import_uafx_bridge_export.py` | Bridge export → candidate.json |
| `uaf-bridge/smt/solve_candidate.py` | SMT solve → witness_plan.json |
| `uaf-bridge/runtime/emit_witness_syz.py` | Witness plan → syzkaller witness program |
| `uaf-bridge/mapping/target_registry.py` | Target pack context resolution (bridge side) |
| `targets/*/manifest.json` | Pack metadata, lifecycle templates, syz_call_map |

---

## C. End-to-End Pipeline

### Stage-by-stage flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          STATIC ANALYSIS (UAFX)                             │
│  LLVM passes → cross-entry UAF warnings (raw JSON)                          │
│  Producer: uafx/ext_uaf_warns.py                                            │
│  Output: raw_uafx_*_warning.json                                            │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         BRIDGE EXPORT                                       │
│  Raw warning → enriched bridge-export shape with target metadata            │
│  Producer: uaf-bridge/uafx_fork/tools/export_bridge_candidate.py            │
│  Input: raw_uafx_*_warning.json                                             │
│  Output: uafx_*_bridge_export.json                                          │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     CANDIDATE NORMALIZATION                                 │
│  Bridge export → canonical candidate.json (v1 schema)                       │
│  Producer: uaf-bridge/extractor/import_uafx_bridge_export.py                │
│  Enrichment: entry classification, syscall template generation              │
│  Output: candidate.json (schema_version: candidate/v1)                      │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        SMT SOLVE / WITNESS PLANNING                         │
│  Candidate constraints → Z3 encoding → SAT/UNSAT → witness plan            │
│  Producer: uaf-bridge/smt/encode_candidate.py + solve_candidate.py          │
│  Output: witness_plan.json (schema_version: witness_plan/v1)                │
│  Contains: ordered_steps, barriers, thread assignment, predicates           │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     WITNESS / HARNESS EMISSION                              │
│  Witness plan → syzkaller .syz program + optional C harness                 │
│  Producer: uaf-bridge/runtime/emit_witness_syz.py                           │
│           uaf-bridge/harness/generate_harness.py                            │
│  Output: witness.syz, harness.c (pack-specific)                             │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      STATE MODEL BUILD                                      │
│  candidate.json + witness_plan.json → runtime artifacts                     │
│  Producer: backend/syz-guided/state_model/build_state_model.py              │
│  Reads: target pack manifest for phase classification and resource chains   │
│  Output: state_model_v1.json, target_profile.json, relation_graph_v1.json   │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       SEED SYNTHESIS                                        │
│  State model → syzkaller .prog seed files                                   │
│  Producer: backend/syz-guided/seedgen/synthesize_seeds.py                   │
│  Logic: bootstrap prefix + configure + variant suffixes from manifest       │
│  Output: seed_*.prog files + seed_manifest.json                             │
│  Invariant: immutable bootstrap prefix preserved in all seeds               │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     CAMPAIGN ORCHESTRATION                                  │
│  Seeds → bounded fuzzing loop → scoring → queue management                  │
│  Code: backend/syz-guided/orchestrator/campaign.py                          │
│  Scoring: prefix_valid + resource_chain + phase_progress + target_signal    │
│  Mutation: prefix-safe mutator with relation guard                          │
│  Output: campaign_summary.json                                              │
│  Note: v1 campaign loop is dry-run only (no real syzkaller execution)       │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     RUNTIME EXECUTION (pack-specific lanes)                 │
│  Seeds → syz-execprog → QEMU guest → dmesg → per-seed evidence             │
│  Code: backend/syz-guided/runtime/{io_uring,net}_lane.py                    │
│        backend/syz-guided/vm_validator/run_one.py (KVM)                     │
│  Output: per-seed triage reports, evidence artifacts (6 types)              │
│  Status: io_uring dry-run proven, net guest-capable but blocked             │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        TRIAGE                                               │
│  Crash logs → KASAN parsing → candidate matching → verdict                  │
│  Code: backend/syz-guided/triage/{report,parse_kasan,match_candidate}.py    │
│  Pack-specific: io_uring_verdict.py, io_uring_symbols.py                    │
│                 net_verdict.py, net_symbols.py                              │
│  Output: triage_report_v1.json with verdict (confirmed/plausible/           │
│          insufficient_data/unrelated) or 6-class subsystem-aware verdict    │
│  Net lane adds: repro artifacts, known-bug hygiene, layered verdicting      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## D. Artifact Contract Map

| Artifact | Schema Version | Producer | Consumer | Purpose |
|----------|---------------|----------|----------|---------|
| `raw_uafx_*_warning.json` | n/a | `uafx/ext_uaf_warns.py` | `uafx_fork/tools/export_bridge_candidate.py` | Raw UAFX static analysis warning |
| `*_bridge_export.json` | `export/0.2` | `export_bridge_candidate.py` | `import_uafx_bridge_export.py` | Enriched bridge-export shape with target metadata |
| `candidate.json` | `candidate/v1` | `import_uafx_bridge_export.py` | `build_state_model.py`, `solve_candidate.py` | Canonical candidate with entries, locations, constraints, syscall templates |
| `witness_plan.json` | `witness_plan/v1` | `solve_candidate.py` | `build_state_model.py`, `emit_witness_syz.py` | SAT/UNSAT result with ordered steps, barriers, thread assignment |
| `witness.syz` | n/a | `emit_witness_syz.py` | `syz-execprog` (optional) | Syzkaller-format witness program |
| `harness.c` | n/a | `generate_harness.py` | Manual compilation | C harness (KVM-specific + generic) |
| `state_model_v1.json` | `state_model/v1` | `build_state_model.py` | `synthesize_seeds.py`, `campaign.py`, `report.py` | Runtime state: phases, resource chains, prefix, score weights |
| `target_profile.json` | `target_profile/v1` | `build_state_model.py` | `report.py`, `match_candidate.py` | Focus frames/files, free/use hints, preferred syscalls |
| `relation_graph_v1.json` | `relation_graph/v1` | `build_state_model.py` | `campaign.py`, `relation_guard.py` | Node/edge graph of resources, syscalls, constraints |
| `seed_*.prog` | n/a | `synthesize_seeds.py` | `syz-execprog`, `campaign.py` | Syzkaller .prog format seeds |
| `seed_manifest.json` | `seed_manifest/v1` | `synthesize_seeds.py` | Campaign orchestrator | Seed inventory metadata |
| `campaign_summary.json` | n/a | `campaign.py` | Operator / triage | Campaign lifecycle stats |
| `triage_report_v1.json` | `triage_report/v1` | `report.py` | Operator | Crash classification with verdict, match score, evidence |
| `runtime_verdict.json` | n/a | `io_uring_lane.py`, `net_lane.py` | Operator | Aggregate verdict from runtime lane |
| Evidence artifacts (6 types) | n/a | Runtime lanes | Operator | execution_trace, prefix_report, coverage, concurrency, alignment, verdict |

### Key contract invariants

1. `candidate.json` and `witness_plan.json` are the **stable bridge→backend handoff boundary**
2. Field meanings must not change silently — additive extensions only
3. Ordering semantics (bootstrap before configure before trigger) are hard constraints
4. Every runtime artifact must reference its source artifacts
5. Schema versions are pinned at v1; no version bumps have occurred

---

## E. Runtime Architecture

### How execution actually happens

There are three runtime execution paths, each at different maturity:

#### Path 1: KVM vm_validator (macOS TCG / Linux KVM)

```
vm_validator/run_one.py orchestrates:
  1. preflight.py — check kernel/disk/key/syz-execprog existence
  2. vm_runner.py — boot QEMU (TCG on macOS, KVM on Linux) with arm64 kernel
  3. prog_injector.py — SCP seed + syz-execprog into guest, SSH execute
  4. log_collector.py — SSH dmesg collection, KASAN extraction
  5. triage/report.py — crash matching against candidate
  6. vm_runner.shutdown_vm() — graceful SSH poweroff or SIGTERM
```

**Status**: Proven on macOS TCG (boots, executes, triages with insufficient_data). Not tested on Linux KVM.

#### Path 2: io_uring runtime lane

```
runtime/io_uring_lane.py:
  For each seed:
    1. Execute via syz-execprog (or mock in dry-run)
    2. Collect dmesg
    3. Run per-seed triage
    4. Emit per-seed evidence
  Aggregate:
    1. Emit 6 evidence artifacts
    2. Classify via io_uring_verdict.py (6 verdict classes)
    3. Emit runtime_verdict.json
```

**Status**: Dry-run proven with synthetic KASAN crash. No live execution yet.

#### Path 3: net (nf_tables) live lane

```
scripts/run_net_vm_campaign.sh (8-step pipeline):
  1. Bridge export → candidate → witness plan
  2. State model build
  3. Seed synthesis
  4. Strict live preflight (host + guest checks)
  5. Single-seed validation
  6. Four-seed validation
  7. Short bounded campaign
  8. Optional extended fuzzing

runtime/net_lane.py drives guest execution:
  - SSH into arm64 QEMU guest
  - Stage seeds
  - Execute via guest-resident syz-execprog
  - Collect dmesg
  - Three-layer verdicting (execution → crash → candidate evidence)
  - Repro reruns for reproducibility classification
  - Known-bug hygiene gating
```

**Status**: Guest-capable. Reached real SSH + seed staging. Blocked on guest tooling validation and per-seed timeout tuning under TCG.

### VM/Guest/Syzkaller pieces

- **QEMU**: `qemu-system-aarch64` with `-machine virt -cpu cortex-a57`
  - macOS: TCG only (software emulation, slow)
  - Linux: KVM acceleration available with `/dev/kvm`
- **Kernel**: arm64 Image (7.0.0-rc5, 148 MB) in `syzkaller-runtime-export/`
  - nftables-enabled variant: `syzkaller-runtime-export/kernel-export/nftables-enabled-Image`
- **Disk images**:
  - `arm64-standalone.qcow2` (11.5 GiB) — full Ubuntu, slow boot, legacy
  - `arm64-live-ready.qcow2` — minimal overlay with fast init, preferred for net lane
- **syzkaller tools**: Built from `syzkaller/` source
  - `syz-execprog` — program executor (46M, reads .prog text files)
  - `syz-executor` — syscall executor (4.1M, connects to execprog via flatrpc)
  - `syz-manager` — campaign manager (72M)
- **Guest networking**: Slirp user-mode (10.0.2.15/24, SSH forwarded to host:10022)

### Host tools required

- `qemu-system-aarch64`
- `ssh`, `scp` (with `-O` legacy mode for minimal guests)
- Python 3.13+ (bridge requires Z3 via pip)
- Go 1.21+ (syzkaller build)
- Optional: cross-compilation for linux/arm64

---

## F. Target Pack Model

### How packs are structured

Each target pack lives under `targets/<pack>/manifest.json` and defines:

```json
{
  "pack": "<name>",
  "subsystem": "<kernel subsystem>",
  "maturity": "<level>",
  "arch": "arm64",
  "target_families": ["<family-id>"],
  "kernel_area_prefixes": ["<path prefix>"],
  "supported_entry_kinds": ["<kind>", ...],
  "lifecycle_templates": ["<pattern>", ...],
  "resource_chain": [{"resource": "...", "producer_call": "...", "consumer_calls": [...]}],
  "phase_calls": {"bootstrap": [...], "configure": [...], "trigger": [...]},
  "seed_variants": [{"name": "...", "suffix": [...]}],
  "syz_call_map": {"<internal_name>": "<syzkaller prog line>"},
  "triage_signal_rules": ["<rule>", ...],
  "fixture_paths": {"raw_warning": "...", "bridge_export": "...", "backend_fixture_dir": "..."}
}
```

The manifest is the **central pack configuration** consumed by:
- `pack_registry.py` (backend) — resolves manifest from candidate metadata
- `target_registry.py` (bridge) — resolves target context for enrichment
- `build_state_model.py` — phase classification, resource chains
- `synthesize_seeds.py` — seed variant generation, call map
- Runtime lanes — `enable_syscalls`, `runtime_config_hints`

### Current pack status

| Pack | Maturity | Manifest | Fixtures | Bridge Tests | Backend Tests | Runtime Lane | Live Execution |
|------|----------|----------|----------|-------------|---------------|-------------|----------------|
| **kvm** | `legacy-initial` | Complete | Complete | Yes | Yes | vm_validator | macOS TCG proven, Linux KVM untested |
| **io_uring** | `runtime-validated(dry-run)` | Complete | Complete | Yes | Yes (34 tests) | io_uring_lane.py | Dry-run only |
| **net** | `runtime-validated(dry-run)` | Complete | Complete | Yes | Yes (34 tests) | net_lane.py | Guest-capable, preflight blocked |
| **bpf** | `scaffolded` | Complete | Complete | Yes | Yes (fixture) | None | None |
| **fs** | `scaffolded` | Complete | Complete | Yes | Yes (fixture) | None | None |

### How a new pack is plugged in

1. Create `targets/<pack>/manifest.json` with metadata, resource chains, syz_call_map
2. Add raw warning fixture: `uaf-bridge/uafx_fork/samples/raw_uafx_<pack>_warning.json`
3. Add bridge export fixture: `uaf-bridge/extractor/sample_uafx_<pack>_bridge_export.json`
4. Add backend fixtures: `backend/syz-guided/tests/fixtures/packs/<pack>/`
5. Add entry kinds to `uaf-bridge/mapping/entry_classifier.py`
6. Add syscall templates to `uaf-bridge/mapping/syscall_templates.py`
7. Run E2E smoke: `bash scripts/e2e_target_pack_smoke.sh --pack <pack>`
8. Optionally add runtime lane, verdict classifier, symbol tables

---

## G. Validation and Test Model

### Test layout

```
uaf-bridge/tests/              # 76 bridge tests (pytest)
  test_bridge_python_selection.py
  test_check_env.py
  test_cli_integration.py
  test_emit_witness_syz.py
  test_export_mock_seed.py
  test_generate_harness.py
  test_import_uafx_bridge_export.py
  test_mock_seed_roundtrip.py
  test_normalize_candidate.py
  test_schema_validation.py
  test_solve_candidate.py
  test_syz_descriptions.py
  test_target_pack_pipeline.py
  test_target_packs_bridge.py
  test_target_packs.py
  test_validate_witness.py

backend/syz-guided/tests/      # 88+ backend tests (unittest)
  test_state_model.py
  test_seedgen.py
  test_score.py
  test_triage.py
  test_relation_guard.py
  test_vm_validator.py          # 30 tests
  test_io_uring_lane.py         # 2 tests
  test_io_uring_verdict.py      # 9 tests
  test_io_uring_seedgen.py      # 9 tests
  test_io_uring_symbols.py      # 13 tests
  test_net_lane.py              # 2 tests
  test_net_verdict.py           # 9 tests
  test_net_seedgen.py           # 9 tests
  test_net_symbols.py           # 13 tests
  test_packs_backend.py         # pack fixture dry-run proofs

tests/                          # Root-level integration
  test_verifier_workflow.py
```

### Smoke scripts

| Script | Purpose | Hardware required |
|--------|---------|-------------------|
| `backend/syz-guided/scripts/smoke_seedgen.sh` | Seed synthesis validation | None |
| `backend/syz-guided/scripts/smoke_campaign.sh` | Campaign lifecycle validation | None |
| `backend/syz-guided/scripts/smoke_triage.sh` | Triage pipeline validation | None |
| `backend/syz-guided/scripts/smoke_pack.sh --pack <X>` | Pack-specific dry-run proof | None |
| `backend/syz-guided/scripts/smoke_vm_validator.sh` | VM validator (TCG) | macOS/Linux |
| `scripts/e2e_target_pack_smoke.sh --pack <X>` | UAFX-first E2E dry-run proof | None |
| `scripts/e2e_witness_smoke.sh` | Bridge witness-only smoke | None |
| `scripts/e2e_harness_smoke.sh` | Bridge harness-only smoke | None |

### E2E entrypoints

| Entrypoint | What it proves |
|------------|----------------|
| `scripts/e2e_target_pack_smoke.sh --pack io_uring` | raw warning → bridge export → candidate → plan → witness → backend artifacts → seeds → campaign → triage |
| `backend/syz-guided/scripts/run_io_uring_vm_campaign.sh` | Bridge through real runtime verdict on arm64 VM |
| `backend/syz-guided/scripts/run_net_vm_campaign.sh` | Bridge through live guest execution with strict preflight |
| `backend/syz-guided/scripts/run_linux_kvm_one_shot.sh` | One-shot seed execution under QEMU/KVM |
| `backend/syz-guided/scripts/run_linux_syz_manager.sh` | Bounded syz-manager campaign |

### Trusted commands (canonical validation)

```bash
# Bridge tests
cd uaf-bridge && .venv_ci/bin/python -m pytest

# Backend tests
python3 backend/syz-guided/tests/test_state_model.py -v
python3 backend/syz-guided/tests/test_seedgen.py -v
python3 backend/syz-guided/tests/test_triage.py -v
python3 backend/syz-guided/tests/test_vm_validator.py -v

# Smoke suite
bash backend/syz-guided/scripts/smoke_seedgen.sh
bash backend/syz-guided/scripts/smoke_campaign.sh
bash backend/syz-guided/scripts/smoke_triage.sh
bash backend/syz-guided/scripts/smoke_pack.sh --pack kvm

# E2E per-pack
bash scripts/e2e_target_pack_smoke.sh --pack io_uring
```

---

## H. Current Truth

### What is definitely working

- Full dry-run artifact pipeline for all 5 packs (kvm, io_uring, net, bpf, fs)
- 76 bridge tests + 88+ backend tests pass
- All smoke scripts pass without special hardware
- State model generation is deterministic and schema-validated
- Seed synthesis preserves immutable bootstrap prefix for all packs
- Prefix-safe mutation preserves prefix and sticky calls
- Relation guard validates resource chain integrity
- KASAN log parsing extracts crash type, stack frames, source files
- Candidate matching scores crashes against focus frames/files/free-use hints
- Triage report emission with structured verdict classification
- macOS QEMU TCG boots arm64 kernel to SSH-ready
- syz-execprog parses .prog files and executes syscalls in guest
- io_uring runtime lane with 6 evidence artifact types and 6 verdict classes
- net runtime lane with 3-layer verdicting, repro, and known-bug hygiene
- All JSON schemas validate (state_model, target_profile, relation_graph, triage_report)

### What is partially working

- **Net live guest execution**: SSH works, seed staging works, but strict preflight still fails on guest tooling checks. The nftables-enabled kernel boots, but some SSH probe windows are too aggressive under TCG
- **VM validator**: Proven on macOS TCG with expected `insufficient_data` verdict. Shell scripts for Linux KVM exist but are untested on real Linux hosts
- **syz-manager integration**: Scripts exist (`run_linux_syz_manager.sh`) but have never been run on a real campaign

### What is blocked

- **Real KASAN crash trigger**: Requires Linux arm64 KVM host with `/dev/kvm` — no KVM available on macOS
- **Coverage signal integration**: KCOV/syzkaller coverage feedback not yet wired into the campaign loop
- **syz-manager bounded campaign**: Shell script ready but untested
- **Repro wrapper on real crash**: The repro module (`repro/candidate_repro.py`) exists but has no real crash input to validate against
- **Guest tooling under TCG**: syz-execprog/syz-executor in the net guest overlay still failing validation checks under TCG's slow emulation

---

## I. Technical Debt / Inconsistencies (ranked by importance)

### 1. Campaign orchestrator is a dry-run stub (HIGH)

`campaign.py:118-148` — the campaign loop picks a parent, scores it, and updates the queue, but **never actually executes anything**. The comment says "In v1 the actual syzkaller execution is stubbed." This is the biggest gap between the designed architecture and the actual implementation.

### 2. No real crash has been triggered (HIGH)

The entire triage pipeline has only been tested against synthetic/fixture crashes. Until a real KASAN UAF is triggered by Madelin-synthesized seeds, the triage matching logic is unvalidated against real-world crash formats and frame naming.

### 3. Naming boundary: syz_call_map vs state_model (MEDIUM)

Seeds use syzkaller lowercase format (`openat$kvm`) while the state model uses uppercase internal names (`openat$KVM`). The `call_aliases` field in manifests and `_normalize_call()` in campaign.py handle this, but it's fragile and only covers `openat$kvm→openat$KVM`. Other packs may have similar issues.

### 4. sys.path manipulation everywhere (MEDIUM)

Every backend module inserts its parent into `sys.path` at import time (e.g., `sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))`). This works but is fragile and prevents proper package installation.

### 5. Dead `MOCK_ROOT` references in smoke scripts (LOW)

`scripts/e2e_witness_smoke.sh` and `scripts/e2e_harness_smoke.sh` contain stale `MOCK_ROOT` variable references. Scripts stop before reaching those branches so it's cosmetic.

### 6. `vm_runner.py` hardcodes `-accel tcg` (LOW)

The Python VM runner always uses TCG acceleration. A small change to accept an `accel` parameter would make it reusable for KVM.

### 7. Bridge venv committed (LOW)

`uaf-bridge/.venv_sys/` is a full Python venv with pip, pytest, etc. committed to the repo. This adds ~3800 files of vendored Python packages.

### 8. Large binary assets in repo (LOW)

`madelin-full-backup.tar.gz` (667 MB) is in the repo root. `syzkaller-runtime-export/` contains a 148 MB kernel Image and 11.5 GB disk image. These should ideally be in LFS or external storage.

### 9. Scaffold-only packs (bpf, fs) (LOW)

bpf and fs packs have manifests, fixtures, and dry-run proofs but no runtime lanes, no subsystem-specific verdict classifiers, and no symbol tables. They follow the contract but cannot execute.

---

## J. Recommended Next Investigation Areas

### Immediate (would unblock progress)

1. **`backend/syz-guided/runtime/net_lane.py:300-500`** — Trace the exact SSH probe timeout logic to understand why guest checks fail under TCG. The strict preflight's timeout windows may need tuning for slow emulation.

2. **`backend/syz-guided/integration/syzkaller_runner.py`** — Read this file to understand if there's any real syzkaller execution integration beyond the dry-run stub in campaign.py.

3. **`syzkaller-runtime-export/arm64-live-ready.qcow2`** inspection — Verify what guest tooling is actually present. The overlay's `/root/syz-execprog` and `/root/syz-executor` need to be confirmed as valid linux/arm64 binaries.

4. **`backend/syz-guided/repro/candidate_repro.py`** — Read this to understand the repro wrapper's design and what it needs from a real crash to function.

### Near-term (would improve system confidence)

5. **`uaf-bridge/smt/encode_candidate.py`** — Understand the exact Z3 encoding to assess how well the SMT constraints model real concurrent UAF patterns.

6. **`backend/syz-guided/orchestrator/score.py`** — Understand the scoring formula to assess whether it would meaningfully guide a real campaign toward the candidate.

7. **`uaf-bridge/mapping/syscall_templates.py`** — Understand how syscall templates are generated per entry kind, and whether the templates are realistic for kernel execution.

8. **Linux KVM host execution** — The three helper scripts (`check_linux_kvm_host.sh`, `run_linux_kvm_one_shot.sh`, `run_linux_syz_manager.sh`) have never been tested on a real Linux host. This is the fastest path to a real validation result.

### Architectural (for future evolution)

9. **Coverage signal integration design** — The scoring system has `target_signal` weight (0.15) but no actual coverage feedback. Designing how KCOV data flows into the scoring loop would be the next major architectural step.

10. **Campaign→syzkaller integration** — Decide whether the campaign loop should drive syz-manager (external process) or embed syz-execprog calls directly. The current stub doesn't commit to either approach.

---

## K. UAFX Static Analysis Detail

UAFX (`uafx/`) is a standalone LLVM-based static analysis tool for discovering cross-entry Use-After-Free candidates in C/C++ code (primarily the Linux kernel). It is built on top of SUTURE and runs as an LLVM `opt` pass.

### How it works

1. **Input**: LLVM bitcode (`.bc`) compiled from kernel source + entry function config file
2. **LLVM Pass**: `libSoundyAliasAnalysis.so` loaded via `opt -load`
3. **Analysis**: Tracks pointer alias relationships across entry functions using Escape-Fetch analysis:
   - **Escape**: memory object stored to a global/shared location in one entry function
   - **Fetch**: same object loaded from that location in a different entry function
   - If the object is freed in the escape path and used in the fetch path → UAF candidate
4. **Validation**: Lockset analysis checks whether concurrent access is feasible (same locks → UAF possible)
5. **Output**: Raw warning JSON with free/use sites, entry functions, call contexts, flow classification (Seq/Con)

### Key LLVM analysis components

| Component | File | Purpose |
|-----------|------|---------|
| `UAFDetector` | `SoundyAliasAnalysis/src/bug_detectors/UAFDetector.cpp` | Core: detect loads from freed memory |
| `AliasAnalysisVisitor` | `SoundyAliasAnalysis/src/AliasAnalysisVisitor.cpp` | Track points-to through stores/loads/calls |
| `FieldTaint` | `SoundyAliasAnalysis/include/TaintInfo.h` | Object-level taint tracking across entries |
| `LocksetAnalysisVisitor` | `SoundyAliasAnalysis/src/LocksetAnalysisVisitor.cpp` | Validate concurrent access patterns |
| `KernelFunctionChecker` | `LinuxKernelCustomizations/src/KernelFunctionChecker.cpp` | Linux-specific function classification |

### Current state

UAFX is a **mature, standalone tool** imported into the monorepo. It has its own benchmark suite (10 test cases). The Madelin project does not modify UAFX — it consumes its raw warning output via the bridge.

### Warning format (raw output)

```json
{
  "warn_data": {
    "by": "UAFDetector",
    "hint": "Con|Seq",
    "loc0": {"loc": [{"at_file": "...", "at_line": N}], "at_func": "...", "ctx": [...]},
    "loc1": {"loc": [{"at_file": "...", "at_line": N}], "at_func": "...", "ctx": [...]},
    "ep0": {"so": "source", "do": "dest", "paths": [...]},
    "ep1": {"so": "source", "do": "dest", "paths": [...]}
  }
}
```

---

## L. SMT Encoding Detail

The bridge's SMT solver (`uaf-bridge/smt/`) uses Z3 Optimize to check structural feasibility of UAF candidates.

### Encoding (`encode_candidate.py`)

For each candidate, the solver creates:
- **Time variables**: `t_<event>` (Int) for each event (init_resource, escape, free, fetch, use, cleanup)
- **Thread variables**: `th_<event>` (Int) for each event
- **Hard constraints**:
  - `t >= 0` and `0 <= th < min_threads` for all events
  - `Distinct(t_e1, t_e2, ...)` — all events happen at distinct times
  - `t_before < t_after` for each partial order edge
- **Soft constraint**: When flow=Con and min_threads >= 2, prefer free/use on different threads

### Solving (`solve_candidate.py`)

1. Encode candidate → Z3 Optimize problem
2. `optimizer.check()` → SAT/UNSAT
3. On SAT: extract model values for time/thread vars
4. `extract_schedule.py`: topological sort → deterministic `ordered_steps[]` + `threads[]` + `barriers[]`
5. Emit `witness_plan.json` with execution hints and debug info

### Key design choice

The SMT encoding is **intentionally structural** — it checks whether the event ordering and threading is feasible, NOT whether the kernel will actually execute those events in that order. Semantic argument synthesis (e.g., what register values to pass) is explicitly out of scope for v1.

---

## Appendix: Architecture Map (One Page)

```
┌──────────────┐    ┌──────────────────┐    ┌─────────────────────────┐
│   UAFX       │    │   uaf-bridge     │    │  backend/syz-guided     │
│   (LLVM)     │───▶│                  │───▶│                         │
│              │    │  export_bridge    │    │  build_state_model      │
│  raw_warning │    │  import_export   │    │  synthesize_seeds       │
│              │    │  normalize       │    │  campaign (dry-run)     │
│              │    │  encode/solve    │    │  prefix_safe_mutator    │
│              │    │  emit_witness    │    │  relation_guard         │
│              │    │  generate_harness│    │  score_program          │
└──────────────┘    │  validate_witness│    │  build_triage_report    │
                    │  target_registry │    │  parse_kasan            │
                    └──────────────────┘    │  match_candidate        │
                                           │                         │
                         Artifacts:        │  Runtime lanes:         │
                    candidate.json ────────│  vm_validator/run_one   │
                    witness_plan.json ─────│  runtime/io_uring_lane  │
                                           │  runtime/net_lane       │
                                           │                         │
                    ┌──────────────────┐   │  Pack resolution:       │
                    │ targets/*/       │───│  pack_registry.py       │
                    │ manifest.json    │   └─────────────────────────┘
                    └──────────────────┘            │
                                                    ▼
                    ┌──────────────────────────────────────┐
                    │  syzkaller (clean upstream)           │
                    │  syz-execprog + syz-executor          │
                    │  syz-manager (for bounded campaigns)  │
                    └──────────────────────────────────────┘
                                    │
                                    ▼
                    ┌──────────────────────────────────────┐
                    │  QEMU arm64 guest                     │
                    │  kernel Image + disk image            │
                    │  KASAN + KCOV enabled                 │
                    │  SSH access (port 10022)              │
                    └──────────────────────────────────────┘
```

---

## Appendix: Where to Start for a New Engineer

1. **Read `README.md`** — 5 minutes. Get the pipeline shape.
2. **Read `context/overview.md` + `context/architecture.md`** — 5 minutes. Get the design intent.
3. **Run the smoke suite** — 10 minutes:
   ```bash
   bash backend/syz-guided/scripts/smoke_seedgen.sh
   bash backend/syz-guided/scripts/smoke_campaign.sh
   bash backend/syz-guided/scripts/smoke_triage.sh
   bash scripts/e2e_target_pack_smoke.sh --pack io_uring
   ```
4. **Read `backend/syz-guided/tests/fixtures/candidate.json`** — Understand the candidate shape.
5. **Read `targets/kvm/manifest.json`** — Understand how packs configure the pipeline.
6. **Trace `build_state_model.py`** — This is the core bridge→backend transformer.
7. **Read `plans/current.md`** — Understand what's been done and what remains.
8. **Read `context/current-status.md`** — Understand the current blockers.

### Canonical commands

```bash
# Run all bridge tests
cd uaf-bridge && .venv_ci/bin/python -m pytest

# Run all backend tests
for f in backend/syz-guided/tests/test_*.py; do python3 "$f" -v; done

# Full E2E proof for a pack
bash scripts/e2e_target_pack_smoke.sh --pack io_uring

# Pack-specific backend smoke
bash backend/syz-guided/scripts/smoke_pack.sh --pack net

# VM validator (macOS TCG)
bash backend/syz-guided/scripts/smoke_vm_validator.sh
```
