#!/usr/bin/env bash
# Smoke test: campaign orchestrator with seed corpus.
# Runs a short bounded campaign (no real syzkaller needed).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
FIXTURES="$BACKEND_DIR/tests/fixtures"
OUT_DIR=$(mktemp -d)

echo "=== smoke_campaign ==="

# Step 1: generate artifacts
python3 "$BACKEND_DIR/state_model/build_state_model.py" \
    --candidate "$FIXTURES/candidate.json" \
    --witness-plan "$FIXTURES/witness_plan.json" \
    --out-dir "$OUT_DIR/artifacts"

echo "  [PASS] artifacts built"

# Step 2: synthesize seeds
python3 "$BACKEND_DIR/seedgen/synthesize_seeds.py" \
    --state-model "$OUT_DIR/artifacts/state_model_v1.json" \
    --out-dir "$OUT_DIR/seeds"

echo "  [PASS] seeds synthesized"

# Step 3: run bounded campaign (10 iterations, no syzkaller)
python3 "$BACKEND_DIR/orchestrator/campaign.py" \
    --artifacts-dir "$OUT_DIR/artifacts" \
    --seeds-dir "$OUT_DIR/seeds" \
    --work-dir "$OUT_DIR/campaign" \
    --max-iterations 10

echo "  [PASS] campaign ran"

# Step 4: verify campaign summary
if [ ! -f "$OUT_DIR/campaign/campaign_summary.json" ]; then
    echo "  [FAIL] campaign_summary.json not found"
    exit 1
fi
echo "  [PASS] campaign summary present"

echo ""
echo "=== smoke_campaign PASSED ==="
echo "Artifacts in: $OUT_DIR"
