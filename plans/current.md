# Current Plan

## Task
Make the arm64 KVM fuzzer path end-to-end runnable and verifiable. The repo already documents a bridge-to-MOCK-to-healer chain, but the current validation story still stops at a mix of artifact generation, importer smoke, and local preflight checks. The goal of this pass is to make the actual launch path trustworthy: bridge artifacts must be produced, imported into MOCK, prepared into a seeded workdir, checked against real runtime prerequisites, and then exercised through the real `cargo run --release -p healer_fuzzer --bin healer -- ...` launch path or stopped early with the exact missing prerequisite.

## Hard Constraints
- preserve the artifact flow `warning -> candidate.json -> witness_plan.json -> witness.syz / MOCK seed`
- do not silently change schemas, field names, or ordering semantics
- keep support claims narrow and explicit; do not broaden the repo beyond what is actually validated
- treat arm64 KVM as the primary target, not a side path
- fail clearly and early on unsupported environments or missing prerequisites
- prefer the smallest safe change needed to make the full validation path repeatable
- do not edit code in this planning pass
- do not disturb unrelated changes already present in the worktree

## Non-Goals
- no architecture redesign
- no schema redesign unless a later implementation step proves it is required
- no expansion to general-purpose fuzzing support
- no claim of “end-to-end validated” unless the real launch path is actually exercised or the blocker is explicit
- no deletion of ambiguous files without proof they are generated, duplicated, obsolete, or unused

## Smallest Relevant File Set
- `plans/repo-map.md`
- `plans/current.md`
- `plans/schema-impact.md` if any artifact contract must change later
- `plans/validation-report.md`
- `context/current-status.md`
- `context/known-issues.md`
- `context/commands.md`
- `context/overview.md`
- `context/architecture.md`
- `context/invariants.md`
- `uaf-bridge/scripts/check_env.py`
- `uaf-bridge/scripts/run_end_to_end_kvm_demo.sh`
- `uaf-bridge/runtime/emit_witness_syz.py`
- `uaf-bridge/runtime/export_mock_seed.py`
- `uaf-bridge/runtime/validate_witness.py`
- `uaf-bridge/extractor/import_uafx_bridge_export.py`
- `uaf-bridge/extractor/normalize_candidate.py`
- `uaf-bridge/smt/solve_candidate.py`
- `mock/tools/import_bridge_seed.py`
- `mock/bridge_seed/importer.py`
- `mock/scripts/_kvm_startup_common.sh`
- `mock/scripts/prepare_kvm_seed.sh`
- `mock/scripts/check_kvm_fuzz_prereqs.sh`
- `mock/scripts/check_remote_target.sh`
- `mock/scripts/run_kvm_seed_fuzz.sh`
- `mock/scripts/run_kvm_seeded_fuzz.sh`
- `mock/README.md`
- `README.md`

## Stage Inputs / Outputs / Prerequisites
### Extraction / Normalization
- Input: raw UAFX warning JSON or bridge-export JSON from `uafx_fork.tools.export_bridge_candidate`
- Output: canonical `candidate.json`
- Prerequisites: Python 3.11+, `jsonschema`, `z3`, repo-local bridge modules importable
- Trust boundary: this stage proves structure, not runtime launchability

### Mapping / Classification
- Input: normalized candidate data
- Output: stable entry classification, support level, and syscall-template selection
- Prerequisites: candidate schema is valid and entry families remain within the explicit narrow arm64 KVM support set
- Trust boundary: unsupported families must remain visibly unsupported

### SMT Solve
- Input: `candidate.json`
- Output: `witness_plan.json`
- Prerequisites: stock Z3 behavior and a valid candidate schema
- Trust boundary: structural feasibility only; no runtime execution proof

### Runtime Emission
- Input: `candidate.json` + `witness_plan.json`
- Output: `witness.syz` and `mock_seed.json`
- Prerequisites: valid witness plan, syzkaller description tree or fixture tree, explicit narrow-KVM witness support
- Trust boundary: emission correctness does not by itself prove the target can run

### MOCK Import / Seed Preparation
- Input: `mock_seed.json`
- Output: `seed_workdir/input/*.prog`, `seed_workdir/relations/bridge_seed.relations`, `seed_workdir/bias.json`, `seed_workdir/imported_seed.json`
- Prerequisites: seed importer available, bridge seed structurally acceptable to MOCK
- Trust boundary: importer success does not prove remote launch readiness

### Remote Target Preflight
- Input: arm64 disk image, SSH key, arm64 kernel image, `SYZ_DIR`, optional host details
- Output: pass/fail preflight only
- Prerequisites: local `cargo`, valid seed workdir, syzkaller layout with `linux_arm64/syz-executor`, remote SSH connectivity, writable temp space, readable `dmesg`, and `gcc` for harness mode
- Trust boundary: preflight is not a launch

### Actual Arm64 KVM Fuzzer Launch
- Input: arm64 disk image, SSH key, arm64 kernel image, seeded workdir, `SYZ_DIR`
- Output: live seeded fuzzing run under `output-kvm-seeded/` or a precise launch failure
- Prerequisites: all earlier stages succeeded plus a real arm64-capable environment
- Trust boundary: this is the first stage that proves runnable end-to-end behavior

## Exact Command Chain For A Real Run
1. `cd /Users/CJ/Desktop/Kernel-stuff/madelin/uaf-bridge && python3 scripts/check_env.py`
2. `cd /Users/CJ/Desktop/Kernel-stuff/madelin/uaf-bridge && bash scripts/run_end_to_end_kvm_demo.sh`
3. `cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock && bash scripts/prepare_kvm_seed.sh`
4. `cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock && export SYZ_DIR="$PWD/target/release/syz-bin"`
5. `cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock && bash scripts/check_kvm_fuzz_prereqs.sh <arm64_disk_image> <ssh_key> <arm64_kernel_image>`
6. `cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock && bash scripts/check_remote_target.sh --mode both --target-host <host> --ssh-key <ssh_key> --syz-dir "$SYZ_DIR"`
7. `cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock && bash scripts/run_kvm_seed_fuzz.sh --dry-run <arm64_disk_image> <ssh_key> <arm64_kernel_image>`
8. `cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock && bash scripts/run_kvm_seed_fuzz.sh --max-seconds 600 <arm64_disk_image> <ssh_key> <arm64_kernel_image>`

## Current Validation Gap
- Static-only verification exists in the bridge tests and schema checks, but that only proves imports, schema shape, and deterministic transforms.
- Smoke-only verification exists in the repo-root witness/harness helpers and shell syntax checks, but that only proves the scripts are wired and the local fixtures are sane.
- Artifact-generation-only verification exists in the bridge demo, which proves `candidate.json`, `witness_plan.json`, `witness.syz`, and `mock_seed.json` can be produced, but it stops before MOCK seed import and the launch path.
- Importer-only verification exists in MOCK-side seed import tests and seed-preparation helpers, which proves the bridge seed can be ingested, but not that the seeded launch can actually start.
- Full executable KVM arm64 run verification is still the missing trust boundary: the repo needs an exercised non-dry-run `run_kvm_seed_fuzz.sh` path on a real arm64-capable environment, or a documented exact blocker when the environment cannot satisfy it.

## Execution Plan
1. Confirm the current end-to-end command chain from the repo map and current docs so the plan follows the real entrypoints, not an invented shortcut.
2. Audit the validation gap against the five buckets above and record which stage each existing test or script actually proves.
3. Identify the smallest likely implementation touchpoints only if the launch path is missing a fail-fast check, path consistency fix, or argument plumbing needed for repeatability.
4. If any artifact contract or ordering semantics may change, stop and route the change through `plans/schema-impact.md` before editing code.
5. Apply the minimal code or script fix needed to make the chain trustworthy, preserving schemas and ordering semantics.
6. Add or adjust narrow tests or smoke coverage only at the boundary touched by the fix.
7. Run the narrowest relevant validations first, then escalate through artifact generation, importer smoke, remote preflight, dry-run launch wiring, and finally the real launch attempt if the environment permits it.
8. If the environment blocks the real launch, stop at the exact blocker, preserve the runbook, and record the blocker as the last trustworthy stage rather than claiming success.

## Validation Order
1. `python3 scripts/check_env.py` in `uaf-bridge`
2. narrow bridge or seed tests for the touched stage
3. `bash scripts/run_end_to_end_kvm_demo.sh` in `uaf-bridge`
4. `bash scripts/prepare_kvm_seed.sh` in `mock`
5. `bash scripts/check_kvm_fuzz_prereqs.sh ...` in `mock`
6. `bash scripts/check_remote_target.sh ...` in `mock`
7. `bash scripts/run_kvm_seed_fuzz.sh --dry-run ...` in `mock`
8. `bash scripts/run_kvm_seed_fuzz.sh --max-seconds 600 ...` in `mock`

## Done Criteria
- the repo has one clear, documented arm64 KVM validation path from bridge artifacts to the actual healer launch entrypoint
- the path either runs end to end in the current environment or fails early with an exact blocker and exact stage
- no silent schema drift or hidden ordering changes were introduced
- the final documentation makes clear which stage is proven by static checks, which by smoke, which by artifact generation, which by importer smoke, and which by a real launch
- fallback reporting exists for blocked environments so later runs can repeat the same chain without guessing
- `plans/validation-report.md` records what ran, what did not run, and where the true blocker occurred
