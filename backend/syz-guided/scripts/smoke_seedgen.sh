#!/usr/bin/env bash
# Smoke test: state model build + seed synthesis from bridge fixtures.
# Exit on any failure.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
FIXTURES="$BACKEND_DIR/tests/fixtures"
OUT_DIR=$(mktemp -d)

echo "=== smoke_seedgen ==="
echo "Fixtures: $FIXTURES"
echo "Output:   $OUT_DIR"

# Step 1: build state model + target profile + relation graph
python3 "$BACKEND_DIR/state_model/build_state_model.py" \
    --candidate "$FIXTURES/candidate.json" \
    --witness-plan "$FIXTURES/witness_plan.json" \
    --out-dir "$OUT_DIR"

echo "  [PASS] state model built"

# Step 2: validate state model
python3 "$BACKEND_DIR/state_model/validate_state_model.py" "$OUT_DIR/state_model_v1.json"
echo "  [PASS] state model validates"

# Step 3: synthesize seeds
python3 "$BACKEND_DIR/seedgen/synthesize_seeds.py" \
    --state-model "$OUT_DIR/state_model_v1.json" \
    --out-dir "$OUT_DIR/seeds"

echo "  [PASS] seeds synthesized"

# Step 4: verify seeds exist and are non-empty
SEED_COUNT=$(ls "$OUT_DIR/seeds/"*.prog 2>/dev/null | wc -l | tr -d ' ')
if [ "$SEED_COUNT" -eq 0 ]; then
    echo "  [FAIL] no .prog seeds found"
    exit 1
fi
echo "  [PASS] $SEED_COUNT seed files found"

# Step 5: verify manifest
if [ ! -f "$OUT_DIR/seeds/seed_manifest.json" ]; then
    echo "  [FAIL] seed_manifest.json not found"
    exit 1
fi
echo "  [PASS] seed manifest present"

echo ""
echo "=== smoke_seedgen PASSED ==="
echo "Artifacts in: $OUT_DIR"
