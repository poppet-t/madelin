# Schema Impact

## Scope
Cleanup-only restructuring pass. The intended changes are limited to generated caches/build outputs, virtualenvs, egg-info, committed runtime output cleanup, `.gitignore` repair, and possibly non-contract docs/reference cleanup. No candidate, witness-plan, or mock-seed schema edits are planned.

## Producers
- `uaf-bridge/extractor/import_uafx_bridge_export.py` and `uaf-bridge/extractor/normalize_candidate.py` produce `candidate.json`.
- `uaf-bridge/smt/solve_candidate.py` produces `witness_plan.json`.
- `uaf-bridge/runtime/emit_witness_syz.py` and `uaf-bridge/runtime/export_mock_seed.py` consume candidate and witness-plan artifacts and produce runtime outputs.
- `uaf-bridge/mock_adapter/import_seed.py` and `uaf-bridge/mock_adapter/seed_to_mock_program.py` consume `mock_seed.json` and produce adapter outputs.
- `mock/bridge_seed/importer.py` and `mock/bridge_seed/policy.py` produce `seed_workdir` content for MOCK.

## Consumers
- `uaf-bridge/runtime/validate_witness.py` consumes witness artifacts.
- `uaf-bridge/mock_adapter/import_seed.py` and `uaf-bridge/mock_adapter/seed_to_mock_program.py` consume `mock_seed.json`.
- `mock/scripts/check_kvm_fuzz_prereqs.sh`, `mock/scripts/prepare_kvm_seed.sh`, `mock/scripts/run_kvm_seed_fuzz.sh`, `mock/scripts/run_witness.sh`, `mock/scripts/run_harness.sh`, and `mock/scripts/build_harness.sh` consume seed-workdir and runtime artifact locations.
- `scripts/e2e_witness_smoke.sh`, `scripts/e2e_harness_smoke.sh`, `scripts/verify_candidate.sh`, and `scripts/verify_batch.sh` consume the same runtime and seed paths.

## Compatibility Verdict
Compatible. This cleanup plan does not change artifact schemas, field names, ordering semantics, or producer/consumer behavior. The only expected effect is removal or quarantine of generated clutter and repair of ignore rules so tracked build/runtime state does not reappear.

## Required Downstream Updates
- None for artifact consumers or producers.
- If any generated outputs are deleted from version control, update `.gitignore` so the same paths stay untracked on future runs.
- If a future cleanup pass flattens `docs/plans/docs/plans/*`, update the README and plan references first; that is a documentation-path migration, not a schema change.

## Notes
- The cleanup plan is explicitly `no-schema-drift`.
- If a later diff touches `candidate.json`, `witness_plan.json`, `mock_seed.json`, or ordering semantics, this assessment must be revisited and expanded into a real contract-impact review.
