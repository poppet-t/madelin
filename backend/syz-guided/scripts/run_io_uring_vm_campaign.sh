#!/usr/bin/env bash
# run_io_uring_vm_campaign.sh — Real io_uring runtime lane on a normal arm64 Linux VM.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(cd "$BACKEND_DIR/../.." && pwd)"
BRIDGE_ROOT="$REPO_ROOT/uaf-bridge"

if [[ -f "$BRIDGE_ROOT/scripts/_bridge_python.sh" ]]; then
  # shellcheck disable=SC1091
  source "$BRIDGE_ROOT/scripts/_bridge_python.sh"
else
  echo "Missing bridge python selector at $BRIDGE_ROOT/scripts/_bridge_python.sh" >&2
  exit 1
fi

usage() {
  cat >&2 <<'USAGE'
Usage: run_io_uring_vm_campaign.sh \
  --syz-execprog <path> \
  --syz-executor <path> \
  [--bridge-export <path>] \
  [--out-dir <path>] \
  [--timeout-sec <seconds>] \
  [--procs <n>] \
  [--threaded] \
  [--dmesg-cmd "dmesg"]

This script runs the full io_uring validation chain on an ordinary arm64 Linux VM:
bridge export -> candidate -> witness plan -> state model -> seeds -> bounded campaign -> real runtime lane.
USAGE
  exit 2
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

SYZ_EXECPROG=""
SYZ_EXECUTOR=""
BRIDGE_EXPORT="$BRIDGE_ROOT/extractor/sample_uafx_io_uring_bridge_export.json"
OUT_DIR="$REPO_ROOT/out/io_uring-runtime/latest"
TIMEOUT_SEC=90
PROCS=1
THREADED=0
DMESG_CMD="dmesg"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --syz-execprog) SYZ_EXECPROG="${2:-}"; shift 2 ;;
    --syz-executor) SYZ_EXECUTOR="${2:-}"; shift 2 ;;
    --bridge-export) BRIDGE_EXPORT="${2:-}"; shift 2 ;;
    --out-dir) OUT_DIR="${2:-}"; shift 2 ;;
    --timeout-sec) TIMEOUT_SEC="${2:-}"; shift 2 ;;
    --procs) PROCS="${2:-}"; shift 2 ;;
    --threaded) THREADED=1; shift ;;
    --dmesg-cmd) DMESG_CMD="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown argument: $1" >&2; usage ;;
  esac
done

[[ -n "$SYZ_EXECPROG" ]] || usage
[[ -n "$SYZ_EXECUTOR" ]] || usage

[[ -f "$SYZ_EXECPROG" ]] || { echo "Missing syz-execprog: $SYZ_EXECPROG" >&2; exit 1; }
[[ -f "$SYZ_EXECUTOR" ]] || { echo "Missing syz-executor: $SYZ_EXECUTOR" >&2; exit 1; }
[[ -f "$BRIDGE_EXPORT" ]] || { echo "Missing bridge export: $BRIDGE_EXPORT" >&2; exit 1; }

require_cmd python3
BRIDGE_PYTHON="$(select_bridge_python "$BRIDGE_ROOT")"

mkdir -p "$OUT_DIR"
BRIDGE_OUT="$OUT_DIR/bridge"
ARTIFACTS_OUT="$OUT_DIR/artifacts"
SEEDS_OUT="$OUT_DIR/seeds"
CAMPAIGN_OUT="$OUT_DIR/campaign"
RUNTIME_OUT="$OUT_DIR/runtime"
mkdir -p "$BRIDGE_OUT" "$ARTIFACTS_OUT" "$SEEDS_OUT" "$CAMPAIGN_OUT" "$RUNTIME_OUT"

CANDIDATE_PATH="$BRIDGE_OUT/candidate.json"
PLAN_PATH="$BRIDGE_OUT/witness_plan.json"
WITNESS_PATH="$BRIDGE_OUT/witness.syz"
HARNESS_PATH="$BRIDGE_OUT/harness.c"

echo "[io_uring] 1/8 import bridge export -> candidate"
(
  cd "$BRIDGE_ROOT"
  "$BRIDGE_PYTHON" -m extractor.import_uafx_bridge_export --input "$BRIDGE_EXPORT" --output "$CANDIDATE_PATH"
)

echo "[io_uring] 2/8 solve candidate -> witness plan"
(
  cd "$BRIDGE_ROOT"
  "$BRIDGE_PYTHON" -m smt.solve_candidate --input "$CANDIDATE_PATH" --output "$PLAN_PATH"
)

echo "[io_uring] 3/8 emit witness + harness"
(
  cd "$BRIDGE_ROOT"
  "$BRIDGE_PYTHON" -m runtime.emit_witness_syz --candidate "$CANDIDATE_PATH" --plan "$PLAN_PATH" --output "$WITNESS_PATH"
  "$BRIDGE_PYTHON" -m harness.generate_harness --candidate "$CANDIDATE_PATH" --plan "$PLAN_PATH" --output "$HARNESS_PATH"
)

echo "[io_uring] 4/8 build backend artifacts"
python3 "$BACKEND_DIR/state_model/build_state_model.py" \
  --candidate "$CANDIDATE_PATH" \
  --witness-plan "$PLAN_PATH" \
  --out-dir "$ARTIFACTS_OUT"

echo "[io_uring] 5/8 synthesize seeds"
python3 "$BACKEND_DIR/seedgen/synthesize_seeds.py" \
  --state-model "$ARTIFACTS_OUT/state_model_v1.json" \
  --out-dir "$SEEDS_OUT"

echo "[io_uring] 6/8 bounded campaign (artifact-level)"
python3 "$BACKEND_DIR/orchestrator/campaign.py" \
  --artifacts-dir "$ARTIFACTS_OUT" \
  --seeds-dir "$SEEDS_OUT" \
  --work-dir "$CAMPAIGN_OUT" \
  --max-iterations 20

RUNTIME_ARGS=(
  --state-model "$ARTIFACTS_OUT/state_model_v1.json"
  --target-profile "$ARTIFACTS_OUT/target_profile.json"
  --seeds-dir "$SEEDS_OUT"
  --syz-execprog "$SYZ_EXECPROG"
  --syz-executor "$SYZ_EXECUTOR"
  --out-dir "$RUNTIME_OUT"
  --timeout-sec "$TIMEOUT_SEC"
  --procs "$PROCS"
  --dmesg-cmd "$DMESG_CMD"
)
if [[ "$THREADED" -eq 1 ]]; then
  RUNTIME_ARGS+=(--threaded)
fi

echo "[io_uring] 7/8 real runtime lane"
python3 "$BACKEND_DIR/runtime/io_uring_lane.py" "${RUNTIME_ARGS[@]}"

echo "[io_uring] 8/8 summary"
python3 - <<'PY' "$OUT_DIR"
import json
import pathlib
import sys
base = pathlib.Path(sys.argv[1])
runtime = json.loads((base / "runtime" / "runtime_verdict.json").read_text())
trace = json.loads((base / "runtime" / "execution_trace_summary.json").read_text())
print("Runtime verdict:", runtime["verdict_class"])
print("Seeds executed:", trace["seeds_executed"], "/", trace["seed_count"])
print("Crashes detected:", trace["crashes_detected"])
print("Timeouts:", trace["timeouts"])
print("Artifacts:", base)
PY
