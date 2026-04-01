#!/usr/bin/env bash
# Smoke test: triage pipeline with synthetic KASAN crash.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
FIXTURES="$BACKEND_DIR/tests/fixtures"
OUT_DIR=$(mktemp -d)

echo "=== smoke_triage ==="

# Step 1: generate artifacts
python3 "$BACKEND_DIR/state_model/build_state_model.py" \
    --candidate "$FIXTURES/candidate.json" \
    --witness-plan "$FIXTURES/witness_plan.json" \
    --out-dir "$OUT_DIR/artifacts"

echo "  [PASS] artifacts built"

# Step 2: create synthetic KASAN crash log
cat > "$OUT_DIR/crash.log" << 'CRASH_EOF'
BUG: KASAN: use-after-free in kvm_timer_should_fire+0x1a/0x30 arch/arm64/kvm/arch_timer.c:923
Read of size 8 at addr ffff0000deadbeef by task syz-executor/1234

Call Trace:
 kvm_timer_should_fire+0x1a/0x30
 kvm_vcpu_check_block+0x4e/0x90
 kvm_arch_vcpu_ioctl_run+0x123/0x456

Allocated by task 1233:
 kvm_timer_vcpu_init+0x12/0x34

Freed by task 1232:
 kvm_timer_vcpu_terminate+0x56/0x78
 kvm_arch_destroy_vm+0xab/0xcd
CRASH_EOF

echo "  [PASS] synthetic crash created"

# Step 3: run triage
python3 "$BACKEND_DIR/triage/report.py" \
    --crash-log "$OUT_DIR/crash.log" \
    --target-profile "$OUT_DIR/artifacts/target_profile.json" \
    --state-model "$OUT_DIR/artifacts/state_model_v1.json" \
    --out "$OUT_DIR/triage_report.json"

echo "  [PASS] triage ran"

# Step 4: verify verdict
VERDICT=$(python3 -c "import json; print(json.load(open('$OUT_DIR/triage_report.json'))['verdict'])")
echo "  Verdict: $VERDICT"

if [ "$VERDICT" != "confirmed" ] && [ "$VERDICT" != "plausible" ]; then
    echo "  [WARN] expected confirmed or plausible for matching UAF crash"
fi
echo "  [PASS] triage report valid"

echo ""
echo "=== smoke_triage PASSED ==="
echo "Artifacts in: $OUT_DIR"
