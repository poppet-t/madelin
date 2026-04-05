#!/usr/bin/env bash
# Smoke test: pack-scoped dry-run backend proof (no real syzkaller or kernel needed).
set -euo pipefail

usage() {
  echo "Usage: $0 --pack <kvm|io_uring|net|bpf|fs>" >&2
  exit 2
}

PACK=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --pack) PACK="${2:-}"; shift 2 ;;
    *) usage ;;
  esac
done

if [[ -z "$PACK" ]]; then
  usage
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
OUT_DIR=$(mktemp -d)

if [[ "$PACK" == "kvm" ]]; then
  FIXTURES="$BACKEND_DIR/tests/fixtures"
else
  FIXTURES="$BACKEND_DIR/tests/fixtures/packs/$PACK"
fi

echo "=== smoke_pack ==="
echo "Pack:     $PACK"
echo "Fixtures: $FIXTURES"
echo "Output:   $OUT_DIR"

python3 "$BACKEND_DIR/state_model/build_state_model.py" \
  --candidate "$FIXTURES/candidate.json" \
  --witness-plan "$FIXTURES/witness_plan.json" \
  --out-dir "$OUT_DIR/artifacts"
echo "  [PASS] artifacts built"

python3 "$BACKEND_DIR/state_model/validate_state_model.py" "$OUT_DIR/artifacts/state_model_v1.json"
echo "  [PASS] state model validates"

python3 "$BACKEND_DIR/seedgen/synthesize_seeds.py" \
  --state-model "$OUT_DIR/artifacts/state_model_v1.json" \
  --out-dir "$OUT_DIR/seeds"
echo "  [PASS] seeds synthesized"

python3 "$BACKEND_DIR/orchestrator/campaign.py" \
  --artifacts-dir "$OUT_DIR/artifacts" \
  --seeds-dir "$OUT_DIR/seeds" \
  --work-dir "$OUT_DIR/campaign" \
  --max-iterations 10
echo "  [PASS] campaign ran"

# Synthetic crash tuned per pack so triage hits focus frames/files.
case "$PACK" in
  kvm)
    CRASH_FRAME="kvm_timer_should_fire"
    CRASH_FILE="arch/arm64/kvm/arch_timer.c"
    FREE_FRAME="kvm_timer_vcpu_terminate"
    ;;
  io_uring)
    CRASH_FRAME="__io_submit_flush_completions"
    CRASH_FILE="io_uring/io_uring.c"
    FREE_FRAME="io_ring_ctx_free"
    ;;
  net)
    CRASH_FRAME="nf_tables_dump_set"
    CRASH_FILE="net/netfilter/nf_tables_api.c"
    FREE_FRAME="nf_tables_destroy_set"
    ;;
  bpf)
    CRASH_FRAME="bpf_map_lookup_elem"
    CRASH_FILE="kernel/bpf/syscall.c"
    FREE_FRAME="bpf_link_free"
    ;;
  fs)
    CRASH_FRAME="vfs_get_tree"
    CRASH_FILE="fs/namespace.c"
    FREE_FRAME="put_fs_context"
    ;;
  *)
    echo "Unknown pack: $PACK" >&2
    exit 2
    ;;
esac

cat > "$OUT_DIR/crash.log" <<CRASH_EOF
BUG: KASAN: use-after-free in ${CRASH_FRAME}+0x1a/0x30 ${CRASH_FILE}:123
Read of size 8 at addr ffff0000deadbeef by task syz-executor/1234

Call Trace:
 ${CRASH_FRAME}+0x1a/0x30
 some_helper+0x4e/0x90

Freed by task 1232:
 ${FREE_FRAME}+0x56/0x78
CRASH_EOF
echo "  [PASS] synthetic crash created"

python3 "$BACKEND_DIR/triage/report.py" \
  --crash-log "$OUT_DIR/crash.log" \
  --target-profile "$OUT_DIR/artifacts/target_profile.json" \
  --state-model "$OUT_DIR/artifacts/state_model_v1.json" \
  --out "$OUT_DIR/triage_report.json"
echo "  [PASS] triage ran"

VERDICT=$(python3 -c "import json; print(json.load(open('$OUT_DIR/triage_report.json'))['verdict'])")
echo "  Verdict: $VERDICT"

echo ""
echo "=== smoke_pack PASSED ==="
echo "Artifacts in: $OUT_DIR"
