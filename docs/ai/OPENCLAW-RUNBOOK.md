# OpenClaw Runbook

## Purpose
Use this document when OpenClaw is operating `madelin` on a Linux-capable VPS or workstation.

OpenClaw should use this runbook to:
- preserve artifact contracts and ordering semantics
- run the supported pipeline in the correct order
- avoid false claims about support or validation
- extend target packs without breaking KVM fixtures

## Monorepo Structure

### `uafx/`
Static analysis producer for cross-entry lifetime bug candidates.

### `uaf-bridge/`
Canonical translator and witness planner.

Core contracts:
- UAFX raw warning or bridge export -> `candidate.json`
- `candidate.json` -> `witness_plan.json`
- `candidate.json` + `witness_plan.json` -> runnable witness scaffold (`witness.syz`) and/or micro-harnesses

Note: the bridge may still emit `mock_seed.json` as a bridge artifact, but `mock/` is not a runtime stage.

### `backend/syz-guided/`
Syzkaller-based runtime backend and triage.

Core contracts:
- `candidate.json` + `witness_plan.json` -> `state_model_v1.json` + `target_profile.json` + `relation_graph_v1.json`
- runtime programs -> crash logs -> `triage_report_v1.json`

### `targets/`
Target-pack manifests and fixtures. KVM is a legacy/initial pack; additional packs cover software-reachable subsystems runnable in ordinary arm64 Linux VMs.

### `plans/` and `context/`
`plans/` is task-local coordination and validation evidence.
`context/` is durable scope, invariants, and known issues.

## System Boundaries

### Artifact boundary
Do not break this pipeline:

`warning/bridge-export -> candidate.json -> witness_plan.json -> backend runtime artifacts -> triage_report_v1.json`

### Determinism boundary
- Everything up to the dynamic runtime stage should remain deterministic and reviewable.
- Unsupported cases must fail explicitly; do not broaden support silently via heuristics.

### Truthfulness boundary
- “Validated” means a target pack’s end-to-end proof chain ran successfully and the evidence is recorded in `plans/validation-report.md`.
- “Scaffolded” means fixture-driven artifacts exist but live execution evidence is not yet established.

## Operator Workflow (Hardware-Light Default)

### 1. Bridge environment and fixture artifacts
```bash
cd /path/to/madelin/uaf-bridge
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```

Run the narrow KVM demo (legacy/initial) if needed:
```bash
PYTHON="$PWD/.venv/bin/python" bash scripts/run_end_to_end_kvm_demo.sh
```

### 2. Backend dry-run proof (no special hardware)
```bash
cd /path/to/madelin/backend/syz-guided
bash scripts/smoke_seedgen.sh
bash scripts/smoke_campaign.sh
bash scripts/smoke_triage.sh
```

### 3. io_uring real-runtime validation (arm64 Linux VM)
```bash
# Full 8-step pipeline: bridge export -> candidate -> plan -> artifacts -> seeds -> campaign -> runtime -> verdict
bash backend/syz-guided/scripts/run_io_uring_vm_campaign.sh \
  --syz-execprog <path-to-syz-execprog> \
  --syz-executor <path-to-syz-executor> \
  --threaded --procs 2

# Inspect results:
cat out/io_uring-runtime/latest/runtime/runtime_verdict.json
cat out/io_uring-runtime/latest/runtime/candidate_alignment_report.json
cat out/io_uring-runtime/latest/runtime/execution_trace_summary.json
```

See `plans/io_uring-runtime-proof.md` for the full proof and evidence artifact descriptions.

### 4. net (nf_tables/netfilter) live validation (arm64 QEMU guest)
```bash
# Preferred arm64 QEMU TCG guest path:
# - kernel: prepared arm64 netfilter/nf_tables lab kernel
# - disk:   prepared guest image or overlay
# - guest-resident tooling: /usr/local/bin/syz-execprog + /usr/local/bin/syz-executor
bash backend/syz-guided/scripts/run_net_vm_campaign.sh \
  --kernel syzkaller-runtime-export/kernel-export/nftables-enabled-Image \
  --disk-image /tmp/madelin-nft-debug2.qcow2 \
  --ssh-key out/net-runtime/live-preflight-probe/id_rsa \
  --guest-syz-execprog-path /usr/local/bin/syz-execprog \
  --guest-syz-executor-path /usr/local/bin/syz-executor \
  --single-seed-only \
  --threaded --procs 1 --timeout-sec 180
```

If you need host-side copies of the real guest binaries:
```bash
bash backend/syz-guided/scripts/stage_arm64_guest_tooling.sh \
  --ssh-key out/net-runtime/live-preflight-probe/id_rsa \
  --ssh-port 10022 \
  --out-dir out/net-runtime/guest-tools/linux-arm64
```

Required guest expectations:
- boot args include `console=ttyAMA0`
- guest SSH works non-interactively as `root`
- `/sys/kernel/debug` exists and debugfs can be mounted
- kernel config exposes at least:
  - `CONFIG_KASAN=y`
  - `CONFIG_KCOV=y`
  - `CONFIG_DEBUG_INFO=y`
  - `CONFIG_DEBUG_FS=y`
  - `CONFIG_KCOV_INSTRUMENT_ALL=y`
  - `CONFIG_NETFILTER=y`
  - `CONFIG_NF_TABLES=y`
- `nfnetlink` and `nf_tables` are built in or loadable
- `syz-execprog -help` inside the guest advertises `-coverfile`

Guest readiness notes:
- Keep the boot path reproducible and save the exact console log for every run.
- Use guest-resident linux/arm64 `syz-execprog` and `syz-executor` when possible.
- File staging uses legacy `scp -O` or a bounded SSH stream fallback to avoid SFTP hangs.
- The lab-only workflow is narrow and proof-driven; ranking helpers are advisory only.

Live run stages:
1. strict preflight
2. single-seed validation
3. four-seed validation
4. short bounded campaign
5. optional extended fuzzing

Artifact layout:
- `out/net-runtime/live-YYYYMMDD-HHMMSS/preflight/`
- `out/net-runtime/live-YYYYMMDD-HHMMSS/campaign/`
- `out/net-runtime/live-YYYYMMDD-HHMMSS/runtime/`
- `out/net-runtime/live-YYYYMMDD-HHMMSS/crashes/`
- `out/net-runtime/live-YYYYMMDD-HHMMSS/repro/`
- `out/net-runtime/live-YYYYMMDD-HHMMSS/logs/`

How to inspect the result:
```bash
cat out/net-runtime/latest/preflight/preflight_summary.json
cat out/net-runtime/latest/runtime/guest_environment_summary.json
cat out/net-runtime/latest/runtime/kernel_provenance.json
cat out/net-runtime/latest/runtime/source_frame_summary.json
cat out/net-runtime/latest/runtime/lab_state.json
cat out/net-runtime/latest/runtime/lab_run_bundle.json
cat out/net-runtime/latest/runtime/blocker_report.json
cat out/net-runtime/latest/runtime/execution_evidence_summary.json
cat out/net-runtime/latest/runtime/crash_evidence_summary.json
cat out/net-runtime/latest/runtime/candidate_evidence_summary.json
cat out/net-runtime/latest/runtime/final_verdict.json
find out/net-runtime/latest/repro -name repro_summary.json -maxdepth 3 -print -exec cat {} \;
cat out/net-runtime/latest/crashes/manual_known_bug_review.json
```

Interpretation rules:
- `environment/setup failure`: preflight or boot/SSH requirements failed; do not trust runtime output
- `target not reached`: the seed did not reach meaningful NETLINK_NETFILTER lifecycle phases
- `target reached, no crash`: path reached with preserved prefix/lifecycle but no kernel crash
- `unrelated crash`: crash happened but not in nf_tables/netfilter-relevant paths
- `candidate-correlated live crash`: netfilter-relevant crash without the full validated-bug bar
- `novelty-unchecked bug candidate`: the full real-crash bar passed, but manual duplicate checking is still pending
- `reproducible kernel bug candidate`: the real-crash bar passed and manual review marked `checked-novel`
- `known/likely-duplicate crash candidate`: manual review marked the signature duplicate or fixed upstream

Do not call a crash “new” until `manual_known_bug_review.json` is completed against:
- syzbot netfilter reports
- known fixed bugs
- current tree / patch state

### 4a. Lab-only ranking helpers
These helpers are optional and deterministic. They never count as proof.

```bash
python3 backend/syz-guided/scripts/rank_net_files.py \
  --target-profile out/net-runtime/latest/artifacts/target_profile.json \
  --output out/net-runtime/latest/logs/ranked_files.json

python3 backend/syz-guided/scripts/rank_net_seeds.py \
  --seed-manifest out/net-runtime/latest/seeds/seed_manifest.json \
  --target-profile out/net-runtime/latest/artifacts/target_profile.json \
  --proof-mode controlled \
  --output out/net-runtime/latest/logs/ranked_seeds.json
```

Lab-only support boundary:
- `targets/net/lab/manifest.json` defines the current synthetic/disclosed lab target.
- A confirmed lab bug still requires:
  - KASAN/KCOV-enabled kernel
  - reproducible boot path
  - saved console and dmesg
  - triage report
  - minimized-seed handoff artifact
  - exact source frames
  - real crash signal reproduced at least twice


### 5. Optional: one-shot VM execution
On hosts without `/dev/kvm`, use `vm_validator` (QEMU TCG) for one-shot execution and log capture. On Linux KVM hosts, use the Linux helper scripts for the KVM pack.

## Adding A New Target Pack (Operator-Safe Checklist)
Do not add a pack by only changing docs. Every pack must ship with fixtures and proof.

1. Add pack metadata and fixture pointers under `targets/<pack>/`.
2. Ensure the UAFX export/import path can select the pack deterministically.
3. Add at least one fixture family: bridge export -> candidate -> witness plan.
4. Add at least one end-to-end dry-run proof that reaches `triage_report_v1.json` without special hardware.
5. Update `README.md` maturity table conservatively based on recorded evidence.

## Adding A Real-Runtime Lane (Follow io_uring Pattern)
After the dry-run proof, to add a real-runtime lane for a pack:

1. Add `triage/<pack>_symbols.py` with subsystem-specific symbol tables.
2. Add `triage/<pack>_verdict.py` with subsystem-aware verdict classification.
3. Add `runtime/<pack>_lane.py` following `io_uring_lane.py` structure.
4. Add `scripts/run_<pack>_vm_campaign.sh` for the operator-facing pipeline.
5. Add `enable_syscalls` and `runtime_config_hints` to the pack manifest.
6. Add unit tests for symbols, verdict (all classes), seedgen (prefix preservation), and lane.
7. Create `plans/<pack>-runtime-proof.md` with documented evidence.
8. Update manifest maturity from `scaffolded` to `runtime-validated(dry-run)`.
9. Update `context/current-status.md`, `context/known-issues.md`, and `plans/repo-map.md`.

## Maintenance Rules For OpenClaw
- Preserve `candidate.json` and `witness_plan.json` semantics.
- Do not silently change ordering semantics.
- Keep bridge and runtime as separate stages.
- Run the smallest relevant checks first and record evidence.
