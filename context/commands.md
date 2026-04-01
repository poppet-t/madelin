# Commands

## Read and map repo
- tree -L 3
- find . -maxdepth 3 -type f | sort

## Existing bridge validation
- python3 -m uaf-bridge.extractor
- python3 uaf-bridge/smt/solve_candidate.py
- python3 uaf-bridge/runtime/emit_witness_syz.py

## Backend schema validation
- python3 backend/syz-guided/state_model/validate_state_model.py <path>
- python3 -m pytest backend/syz-guided/tests/test_state_model.py

## Seed generation smoke
- python3 backend/syz-guided/seedgen/synthesize_seeds.py --candidate out/.../candidate.json --witness out/.../witness_plan.json
- bash backend/syz-guided/scripts/smoke_seedgen.sh

## Campaign smoke
- bash backend/syz-guided/scripts/smoke_campaign.sh

## Triage smoke
- bash backend/syz-guided/scripts/smoke_triage.sh

## End-to-end candidate run
- bash backend/syz-guided/scripts/run_kvm_candidate.sh <candidate_dir>