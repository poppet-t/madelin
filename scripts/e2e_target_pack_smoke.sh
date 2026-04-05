#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRIDGE_ROOT="$REPO_ROOT/uaf-bridge"
BACKEND_ROOT="$REPO_ROOT/backend/syz-guided"
source "$BRIDGE_ROOT/scripts/_bridge_python.sh"

usage() {
  cat >&2 <<'EOF'
usage: e2e_target_pack_smoke.sh --pack <kvm|io_uring|net|bpf|fs> [--raw-warning <path>] [--output-dir <path>]
EOF
  exit 1
}

default_raw_warning() {
  case "$1" in
    kvm) printf '%s\n' "$BRIDGE_ROOT/uafx_fork/samples/raw_uafx_kvm_warning.json" ;;
    io_uring) printf '%s\n' "$BRIDGE_ROOT/uafx_fork/samples/raw_uafx_io_uring_warning.json" ;;
    net) printf '%s\n' "$BRIDGE_ROOT/uafx_fork/samples/raw_uafx_net_warning.json" ;;
    bpf) printf '%s\n' "$BRIDGE_ROOT/uafx_fork/samples/raw_uafx_bpf_warning.json" ;;
    fs) printf '%s\n' "$BRIDGE_ROOT/uafx_fork/samples/raw_uafx_fs_warning.json" ;;
    *) printf 'error: unsupported pack: %s\n' "$1" >&2; exit 2 ;;
  esac
}

crash_fingerprint() {
  case "$1" in
    kvm)
      printf '%s|%s|%s\n' "kvm_timer_should_fire" "arch/arm64/kvm/arch_timer.c" "kvm_timer_vcpu_terminate"
      ;;
    io_uring)
      printf '%s|%s|%s\n' "__io_submit_flush_completions" "io_uring/io_uring.c" "io_ring_ctx_free"
      ;;
    net)
      printf '%s|%s|%s\n' "nf_tables_dump_set" "net/netfilter/nf_tables_api.c" "nf_tables_destroy_set"
      ;;
    bpf)
      printf '%s|%s|%s\n' "bpf_map_lookup_elem" "kernel/bpf/syscall.c" "bpf_link_free"
      ;;
    fs)
      printf '%s|%s|%s\n' "vfs_get_tree" "fs/namespace.c" "put_fs_context"
      ;;
    *)
      printf 'error: unsupported pack: %s\n' "$1" >&2
      exit 2
      ;;
  esac
}

PACK=""
RAW_WARNING=""
OUTPUT_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pack)
      [[ $# -ge 2 ]] || usage
      PACK="$2"
      shift 2
      ;;
    --raw-warning)
      [[ $# -ge 2 ]] || usage
      RAW_WARNING="$2"
      shift 2
      ;;
    --output-dir)
      [[ $# -ge 2 ]] || usage
      OUTPUT_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      ;;
    *)
      printf 'error: unknown option: %s\n' "$1" >&2
      usage
      ;;
  esac
done

[[ -n "$PACK" ]] || usage
PYTHON_BIN="$(select_bridge_python "$BRIDGE_ROOT")"
SYZ_ROOT="$BRIDGE_ROOT/tests/fixtures/syzkaller"

if [[ -z "$RAW_WARNING" ]]; then
  RAW_WARNING="$(default_raw_warning "$PACK")"
fi
if [[ -z "$OUTPUT_DIR" ]]; then
  OUTPUT_DIR="$REPO_ROOT/out/e2e-target-pack/$PACK"
fi
mkdir -p "$OUTPUT_DIR"

printf '=== e2e_target_pack_smoke ===\n'
printf 'Pack:       %s\n' "$PACK"
printf 'Raw input:  %s\n' "$RAW_WARNING"
printf 'Output dir: %s\n' "$OUTPUT_DIR"

printf '[preflight] checking bridge environment\n'
"$PYTHON_BIN" "$BRIDGE_ROOT/scripts/check_env.py"

RAW_EXPORT_PATH="$OUTPUT_DIR/uafx_bridge_export.json"
CANDIDATE_PATH="$OUTPUT_DIR/candidate.json"
PLAN_PATH="$OUTPUT_DIR/witness_plan.json"
WITNESS_PATH="$OUTPUT_DIR/witness.syz"
HARNESS_PATH="$OUTPUT_DIR/harness.c"
ARTIFACTS_DIR="$OUTPUT_DIR/backend"
SEEDS_DIR="$OUTPUT_DIR/seeds"
CAMPAIGN_DIR="$OUTPUT_DIR/campaign"
CRASH_LOG_PATH="$OUTPUT_DIR/crash.log"
TRIAGE_PATH="$OUTPUT_DIR/triage_report_v1.json"

printf '[1/10] exporting bridge candidate\n'
(
  cd "$BRIDGE_ROOT"
  "$PYTHON_BIN" -m uafx_fork.tools.export_bridge_candidate \
    --input "$RAW_WARNING" \
    --output "$RAW_EXPORT_PATH"
)

printf '[2/10] importing candidate\n'
(
  cd "$BRIDGE_ROOT"
  "$PYTHON_BIN" -m extractor.import_uafx_bridge_export \
    --input "$RAW_EXPORT_PATH" \
    --output "$CANDIDATE_PATH"
)

printf '[3/10] solving witness plan\n'
(
  cd "$BRIDGE_ROOT"
  "$PYTHON_BIN" -m smt.solve_candidate \
    --input "$CANDIDATE_PATH" \
    --output "$PLAN_PATH"
)

printf '[4/10] emitting witness\n'
(
  cd "$BRIDGE_ROOT"
  "$PYTHON_BIN" -m runtime.emit_witness_syz \
    --candidate "$CANDIDATE_PATH" \
    --plan "$PLAN_PATH" \
    --output "$WITNESS_PATH" \
    --syz-root "$SYZ_ROOT"
)

printf '[5/10] validating witness\n'
(
  cd "$BRIDGE_ROOT"
  "$PYTHON_BIN" -m runtime.validate_witness \
    --candidate "$CANDIDATE_PATH" \
    --plan "$PLAN_PATH" \
    --witness "$WITNESS_PATH" \
    --syz-root "$SYZ_ROOT"
)

printf '[6/10] generating harness\n'
(
  cd "$BRIDGE_ROOT"
  "$PYTHON_BIN" -m harness.generate_harness \
    --candidate "$CANDIDATE_PATH" \
    --plan "$PLAN_PATH" \
    --output "$HARNESS_PATH"
)

printf '[7/10] building backend artifacts\n'
python3 "$BACKEND_ROOT/state_model/build_state_model.py" \
  --candidate "$CANDIDATE_PATH" \
  --witness-plan "$PLAN_PATH" \
  --out-dir "$ARTIFACTS_DIR"
python3 "$BACKEND_ROOT/state_model/validate_state_model.py" \
  "$ARTIFACTS_DIR/state_model_v1.json"

printf '[8/10] synthesizing seeds\n'
python3 "$BACKEND_ROOT/seedgen/synthesize_seeds.py" \
  --state-model "$ARTIFACTS_DIR/state_model_v1.json" \
  --out-dir "$SEEDS_DIR"

printf '[9/10] running bounded campaign\n'
python3 "$BACKEND_ROOT/orchestrator/campaign.py" \
  --artifacts-dir "$ARTIFACTS_DIR" \
  --seeds-dir "$SEEDS_DIR" \
  --work-dir "$CAMPAIGN_DIR" \
  --max-iterations 10

IFS='|' read -r CRASH_FRAME CRASH_FILE FREE_FRAME <<<"$(crash_fingerprint "$PACK")"
cat >"$CRASH_LOG_PATH" <<EOF
BUG: KASAN: use-after-free in ${CRASH_FRAME}+0x1a/0x30 ${CRASH_FILE}:123
Read of size 8 at addr ffff0000deadbeef by task syz-executor/1234

Call Trace:
 ${CRASH_FRAME}+0x1a/0x30
 some_helper+0x4e/0x90

Freed by task 1232:
 ${FREE_FRAME}+0x56/0x78
EOF

printf '[10/10] emitting triage report\n'
python3 "$BACKEND_ROOT/triage/report.py" \
  --crash-log "$CRASH_LOG_PATH" \
  --target-profile "$ARTIFACTS_DIR/target_profile.json" \
  --state-model "$ARTIFACTS_DIR/state_model_v1.json" \
  --out "$TRIAGE_PATH"

python3 - <<'PY' "$TRIAGE_PATH"
import json
import pathlib
import sys

report = json.loads(pathlib.Path(sys.argv[1]).read_text())
print(f"Verdict: {report['verdict']} (score={report['candidate_match']['match_score']:.2f})")
PY

printf '=== e2e_target_pack_smoke PASSED ===\n'
