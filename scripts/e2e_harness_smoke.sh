#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRIDGE_ROOT="$REPO_ROOT/uaf-bridge"
source "$BRIDGE_ROOT/scripts/_bridge_python.sh"

usage() {
  cat >&2 <<'USAGE'
usage: e2e_harness_smoke.sh [--pack <kvm|io_uring|net|bpf|fs>] [--output-dir <path>]

Generates candidate.json, witness_plan.json, and a narrow harness from the in-repo raw UAFX warning for the selected target pack.
USAGE
  exit 1
}

PACK="kvm"
OUTPUT_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pack)
      [[ $# -ge 2 ]] || usage
      PACK="$2"
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
    --*)
      printf 'error: unknown option: %s\n' "$1" >&2
      exit 1
      ;;
    *)
      usage
      ;;
  esac
done

BRIDGE_PYTHON="$(select_bridge_python "$BRIDGE_ROOT")"
RAW_WARNING="$BRIDGE_ROOT/uafx_fork/samples/raw_uafx_${PACK}_warning.json"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/out/e2e-harness-$PACK}"
mkdir -p "$OUTPUT_DIR"

printf '[preflight] checking bridge environment\n'
"$BRIDGE_PYTHON" "$BRIDGE_ROOT/scripts/check_env.py"

EXPORT_PATH="$OUTPUT_DIR/uafx_bridge_export.json"
CANDIDATE_PATH="$OUTPUT_DIR/candidate.json"
PLAN_PATH="$OUTPUT_DIR/witness_plan.json"
HARNESS_PATH="$OUTPUT_DIR/harness.c"

printf '[1/4] exporting bridge artifact from raw warning\n'
(
  cd "$BRIDGE_ROOT"
  "$BRIDGE_PYTHON" -m uafx_fork.tools.export_bridge_candidate --input "$RAW_WARNING" --output "$EXPORT_PATH"
)

printf '[2/4] importing candidate.json\n'
(
  cd "$BRIDGE_ROOT"
  "$BRIDGE_PYTHON" -m extractor.import_uafx_bridge_export --input "$EXPORT_PATH" --output "$CANDIDATE_PATH"
)

printf '[3/4] solving witness plan\n'
(
  cd "$BRIDGE_ROOT"
  "$BRIDGE_PYTHON" -m smt.solve_candidate --input "$CANDIDATE_PATH" --output "$PLAN_PATH"
)

printf '[4/4] generating harness\n'
(
  cd "$BRIDGE_ROOT"
  "$BRIDGE_PYTHON" -m harness.generate_harness --candidate "$CANDIDATE_PATH" --plan "$PLAN_PATH" --output "$HARNESS_PATH"
)

printf 'Harness artifacts ready under %s\n' "$OUTPUT_DIR"
