# Commands

## Environment checks
- `python3 uaf-bridge/scripts/check_env.py`
- `bash mock/scripts/check_remote_target.sh`

## Narrow smoke paths
- `bash scripts/e2e_witness_smoke.sh`
- `bash scripts/e2e_harness_smoke.sh`

## Bridge flow
- `python3 -m extractor ...`
- `python3 uaf-bridge/smt/solve_candidate.py ...`
- `python3 uaf-bridge/runtime/emit_witness_syz.py ...`

## Demo path
- `bash uaf-bridge/scripts/run_end_to_end_kvm_demo.sh`

## MOCK-side import
- `python3 mock/tools/import_bridge_seed.py ...`

## What to run first
1. environment preflight
2. narrow smoke relevant to touched stage
3. stage-specific validation
4. broader end-to-end demo only if needed
