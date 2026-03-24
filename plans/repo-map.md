# Repo Map

## Scope
This map traces the current Linux arm64 KVM validation path end to end: raw warning intake, candidate normalization, SMT solve, runtime emission, MOCK import, seed preparation, remote target preflight, and the actual seeded fuzzing launch. It is deliberately narrower than the whole repo and treats support claims conservatively.

## 1. Extraction / Normalization
- Owner: `uaf-bridge/extractor/`, plus the bridge-side UAFX stub under `uaf-bridge/uafx_fork/`.
- Source files and scripts: `uaf-bridge/uafx_fork/tools/export_bridge_candidate.py`, `uaf-bridge/extractor/import_uafx_bridge_export.py`, `uaf-bridge/extractor/normalize_candidate.py`, `uaf-bridge/extractor/sample_warn_data.json`, `uaf-bridge/extractor/sample_uafx_kvm_bridge_export.json`, `uaf-bridge/scripts/run_end_to_end_kvm_demo.sh`.
- Inputs: raw UAFX warning JSON or the staged bridge-export JSON carrying `loc0`, `loc1`, `flow`, `constraint_summary`, `entry_summary`, and the raw warning payload.
- Outputs: canonical `candidate.json` with `candidate_id`, provenance, `entries[]`, `constraints`, and `status`; the demo path also writes `out/uafx_kvm_bridge_export.json`.
- Trust boundary: this stage is only trustworthy when `candidate.json` validates and the supported KVM/arm64 entry set is still explicit. Unsupported entries remain explicit rather than being inferred away.

## 2. Mapping / Classification
- Owner: `uaf-bridge/mapping/`.
- Source files: `uaf-bridge/mapping/entry_classifier.py`, `uaf-bridge/mapping/syscall_templates.py`, `uaf-bridge/mapping/manual_driver_map.yaml`, and the consumers in `uaf-bridge/extractor/*.py`.
- Inputs: normalized entry contexts from `candidate.json`, plus the manual driver map for grounded classifications.
- Outputs: per-entry `entry_kind`, `support_level`, `syscall_templates`, `grounded` vs `heuristic` provenance, and `status.ready_for_smt`.
- Trust boundary: the repo only claims narrow arm64 KVM support for the supported entry families. If an entry is `unknown`, the candidate should remain visibly unsupported instead of being widened silently.

## 3. SMT Solve
- Owner: `uaf-bridge/smt/`.
- Source files: `uaf-bridge/smt/encode_candidate.py`, `uaf-bridge/smt/extract_schedule.py`, `uaf-bridge/smt/solve_candidate.py`.
- Inputs: `candidate.json`.
- Outputs: `witness_plan.json` with `sat`, `status`, `ordered_steps`, `threads`, `barriers`, `predicates`, `execution_hints`, and `debug`.
- Trust boundary: this stage is structural feasibility only. It uses stock Z3, and it does not synthesize full semantic argument values for a runnable KVM program.

## 4. Runtime Emission
- Owner: `uaf-bridge/runtime/` and the bridge-facing adapter under `uaf-bridge/mock_adapter/`.
- Source files: `uaf-bridge/runtime/emit_witness_syz.py`, `uaf-bridge/runtime/validate_witness.py`, `uaf-bridge/runtime/export_mock_seed.py`, `uaf-bridge/mock_adapter/import_seed.py`, `uaf-bridge/mock_adapter/seed_to_mock_program.py`, `uaf-bridge/mock_adapter/README.md`.
- Inputs: `candidate.json`, `witness_plan.json`, and a syzkaller description tree or fixture tree via `--syz-root`.
- Outputs: `witness.syz`, `mock_seed.json`, the optional adapter JSON/text scaffold, and proof/debug artifacts under `out/uafx_kvm_proof/`.
- Trust boundary: the witness layer is intentionally narrow and only emits the supported arm64 KVM syscall subset. `mock_seed.json` is structural seed intent, not a full runnable reproducer.

## 5. MOCK Import
- Owner: `mock/tools/` and `mock/bridge_seed/`.
- Source files and scripts: `mock/tools/import_bridge_seed.py`, `mock/bridge_seed/importer.py`, `mock/bridge_seed/policy.py`, `mock/bridge_seed/corpus.py`, `mock/bridge_seed/schema.py`.
- Inputs: `mock_seed.json`.
- Outputs: `seed_workdir/input/*.prog`, `seed_workdir/relations/bridge_seed.relations`, `seed_workdir/bias.json`, `seed_workdir/imported_seed.json`, and preview summaries under `seed_workdir/preview/`.
- Trust boundary: import success proves the bridge seed is structurally acceptable to MOCK, but it does not prove the remote KVM workflow can launch.

## 6. Seed Preparation
- Owner: `mock/scripts/`.
- Source files: `mock/scripts/prepare_kvm_seed.sh`, `mock/scripts/_kvm_startup_common.sh`.
- Inputs: bridge-generated `out/uafx_kvm_mock_seed.json`, plus the output seed workdir location.
- Outputs: a populated `seed_workdir` with corpus programs, relation bias, and `bias.json`.
- Trust boundary: this is a bridge-to-MOCK handoff convenience wrapper. It still depends on the bridge demo succeeding first.

## 7. Remote Target Preflight
- Owner: `mock/scripts/`.
- Source files: `mock/scripts/check_kvm_fuzz_prereqs.sh`, `mock/scripts/check_remote_target.sh`, `mock/scripts/_kvm_startup_common.sh`.
- Inputs: arm64 disk image, SSH private key, arm64 kernel image, local `SYZ_DIR`, seed workdir, and optional remote host details.
- Outputs: pass/fail preflight output only.
- Trust boundary: these scripts validate prerequisites and remote reachability, but they do not start fuzzing. `check_kvm_fuzz_prereqs.sh` is local-state focused; `check_remote_target.sh` is SSH/dmesg/gcc focused.

## 8. Actual arm64 KVM Fuzzer Launch
- Owner: `mock/scripts/` and the `healer_fuzzer` crate under `mock/`.
- Source files and scripts: `mock/scripts/run_kvm_seed_fuzz.sh`, `mock/scripts/run_kvm_seeded_fuzz.sh`, `mock/scripts/run_witness.sh`, `mock/scripts/run_harness.sh`, `mock/scripts/build_harness.sh`, `mock/healer_fuzzer/*`, `mock/syz_wrapper/*`, `mock/healer_core/*`.
- Inputs: arm64 disk image, SSH key, arm64 kernel image, populated `seed_workdir`, and `SYZ_DIR`.
- Outputs: `output-kvm-seeded/` by default, including `debug-summary.json`, logs, and any verdict or crash artifacts.
- Trust boundary: this is the first point where the repo attempts a real seeded fuzzing run. `run_kvm_seed_fuzz.sh --dry-run` only checks configuration; the non-dry-run invocation is the actual launch path.

## Exact Command Chain Implied By The Repo
1. `cd /Users/CJ/Desktop/Kernel-stuff/madelin/uaf-bridge && python3 scripts/check_env.py`
2. `cd /Users/CJ/Desktop/Kernel-stuff/madelin/uaf-bridge && bash scripts/run_end_to_end_kvm_demo.sh`
3. `cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock && bash scripts/prepare_kvm_seed.sh`
4. `cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock && export SYZ_DIR="$PWD/target/release/syz-bin"`
5. `cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock && bash scripts/check_kvm_fuzz_prereqs.sh <arm64_disk_image> <ssh_key> <arm64_kernel_image>`
6. `cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock && bash scripts/check_remote_target.sh --mode both --target-host <host> --ssh-key <ssh_key> --syz-dir "$SYZ_DIR"`
7. `cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock && bash scripts/run_kvm_seed_fuzz.sh --dry-run <arm64_disk_image> <ssh_key> <arm64_kernel_image>`
8. `cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock && bash scripts/run_kvm_seed_fuzz.sh --max-seconds 600 <arm64_disk_image> <ssh_key> <arm64_kernel_image>`

The compatibility shim `mock/scripts/run_kvm_seeded_fuzz.sh` forwards directly into `run_kvm_seed_fuzz.sh`.

## Environment Prerequisites And External Dependencies
- `uaf-bridge` needs Python 3.11+, `jsonschema`, `z3` or `z3-solver`, and `pytest` for the bridge-side test slice.
- The bridge demo and witness validation also need the repo-local syzkaller fixture tree under `uaf-bridge/tests/fixtures/syzkaller` or a real syzkaller tree via `SYZ_DIR`.
- `mock` needs a Rust/Cargo toolchain because the actual launch path is `cargo run --release -p healer_fuzzer --bin healer -- ...`.
- The canonical seeded launch path expects `SYZ_DIR` to resolve to a syzkaller tree with `linux_arm64/syz-executor`, `syz-execprog`, `syz-symbolize`, and `syz-repro`.
- Real fuzzing needs an arm64 disk image, an SSH private key for that image, and an arm64 kernel image.
- Remote witness/harness paths additionally need SSH access, writable temp space, readable `dmesg`, and `gcc` on the target for harness mode.
- Building or refreshing the syzkaller tree may require `wget`, `sha384sum`, `unzip`, `patch`, `make`, and `go`.

## Where The Path Becomes Untrustworthy Or Environment-Bound
- `uaf-bridge/scripts/check_env.py` is the first hard gate; if `jsonschema` or `z3` is missing, the bridge stage is not trustworthy.
- `uaf-bridge/scripts/run_end_to_end_kvm_demo.sh` proves artifact generation, but it stops before any MOCK workdir or remote target execution.
- `mock/scripts/prepare_kvm_seed.sh` is still bridge-demo dependent, so it fails as soon as the bridge side fails.
- `mock/scripts/check_kvm_fuzz_prereqs.sh` only checks local files and syzkaller layout; it does not verify the remote target can execute the workflow.
- `mock/scripts/check_remote_target.sh` is preflight only; it does not launch the fuzzer.
- `mock/scripts/run_kvm_seed_fuzz.sh --dry-run` validates the command wiring, not the actual launch.
- The repo does not bundle the arm64 disk image, SSH key, or kernel image, so a real run cannot be claimed without external assets.
- The current workspace already shows the bridge env as fragile because the tracked bridge virtualenv was removed and the available bridge env has missing dependencies.

## What Counts As True End-To-End Validation
- A valid run must produce `candidate.json`, `witness_plan.json`, `witness.syz`, and `mock_seed.json`, import the seed into `seed_workdir`, pass local prereqs, pass remote target preflight, and then execute the non-dry-run `run_kvm_seed_fuzz.sh` path against a real arm64 target.
- The minimum acceptable success signal is that the actual `cargo run --release -p healer_fuzzer --bin healer -- ...` invocation starts and runs on the remote-capable arm64 workflow, with output artifacts written under the requested output directory.
- If the environment blocks the run, the repo should fail early with the exact blocker and the exact stage where it occurred, instead of claiming end-to-end validation.

## Supporting Smoke Paths
- `scripts/e2e_witness_smoke.sh` and `scripts/e2e_harness_smoke.sh` are useful narrow guards, but they stop after artifact generation when a real target or local syzkaller tree is missing.
- `scripts/verify_candidate.sh` and `scripts/verify_batch.sh` are broader orchestration helpers, but they are still validation wrappers around the same bridge and launch stages.
- These scripts are complementary to the seeded KVM workflow, not replacements for the actual seeded launch path.
