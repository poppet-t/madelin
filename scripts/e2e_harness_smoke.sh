#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRIDGE_ROOT="$REPO_ROOT/uaf-bridge"
MOCK_ROOT="$REPO_ROOT/mock"
source "$BRIDGE_ROOT/scripts/_bridge_python.sh"

usage() {
  cat >&2 <<'EOF'
usage: e2e_harness_smoke.sh [--candidate <path>] [--output-dir <path>] [--target-host <host>] [--ssh-key <path>] [--ssh-user <user>] [--ssh-port <port>] [--execute]
EOF
  exit 1
}

detect_bridge_python() {
  select_bridge_python "$BRIDGE_ROOT"
}

CANDIDATE_INPUT=""
OUTPUT_DIR="$REPO_ROOT/out/e2e-harness-smoke"
TARGET_HOST=""
SSH_KEY=""
SSH_USER="root"
SSH_PORT="22"
EXECUTE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --candidate)
      [[ $# -ge 2 ]] || usage
      CANDIDATE_INPUT="$2"
      shift 2
      ;;
    --output-dir)
      [[ $# -ge 2 ]] || usage
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --target-host)
      [[ $# -ge 2 ]] || usage
      TARGET_HOST="$2"
      shift 2
      ;;
    --ssh-key)
      [[ $# -ge 2 ]] || usage
      SSH_KEY="$2"
      shift 2
      ;;
    --ssh-user)
      [[ $# -ge 2 ]] || usage
      SSH_USER="$2"
      shift 2
      ;;
    --ssh-port)
      [[ $# -ge 2 ]] || usage
      SSH_PORT="$2"
      shift 2
      ;;
    --execute)
      EXECUTE=1
      shift
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

PYTHON_BIN="$(detect_bridge_python)"
RAW_EXPORT="$BRIDGE_ROOT/extractor/sample_uafx_kvm_bridge_export.json"

mkdir -p "$OUTPUT_DIR"

printf '[preflight] checking bridge environment\n'
"$PYTHON_BIN" "$BRIDGE_ROOT/scripts/check_env.py"

CANDIDATE_PATH="$OUTPUT_DIR/candidate.json"
PLAN_PATH="$OUTPUT_DIR/witness_plan.json"
HARNESS_PATH="$OUTPUT_DIR/harness.c"

if [[ -n "$CANDIDATE_INPUT" ]]; then
  cp "$CANDIDATE_INPUT" "$CANDIDATE_PATH"
else
  printf '[1/3] importing golden KVM candidate\n'
  (
    cd "$BRIDGE_ROOT"
    "$PYTHON_BIN" -m extractor.import_uafx_bridge_export \
      --input "$RAW_EXPORT" \
      --output "$CANDIDATE_PATH"
  )
fi

printf '[2/3] solving witness plan\n'
(
  cd "$BRIDGE_ROOT"
  "$PYTHON_BIN" -m smt.solve_candidate \
    --input "$CANDIDATE_PATH" \
    --output "$PLAN_PATH"
)

printf '[3/3] generating narrow harness\n'
(
  cd "$BRIDGE_ROOT"
  "$PYTHON_BIN" -m harness.generate_harness \
    --candidate "$CANDIDATE_PATH" \
    --plan "$PLAN_PATH" \
    --output "$HARNESS_PATH"
)

printf 'Artifacts ready under %s\n' "$OUTPUT_DIR"

if [[ -z "$TARGET_HOST" || -z "$SSH_KEY" ]]; then
  printf 'note: no remote target provided; stopping after artifact generation.\n'
  exit 0
fi

printf '[preflight] checking remote harness target\n'
bash "$MOCK_ROOT/scripts/check_remote_target.sh" \
  --mode harness \
  --target-host "$TARGET_HOST" \
  --ssh-key "$SSH_KEY" \
  --ssh-user "$SSH_USER" \
  --ssh-port "$SSH_PORT"

printf '[run] harness smoke path\n'
CMD=(
  bash "$MOCK_ROOT/scripts/run_harness.sh"
  --harness "$HARNESS_PATH"
  --candidate "$CANDIDATE_PATH"
  --target-host "$TARGET_HOST"
  --ssh-key "$SSH_KEY"
  --ssh-user "$SSH_USER"
  --ssh-port "$SSH_PORT"
  --output-dir "$OUTPUT_DIR/run"
)
if [[ "$EXECUTE" -eq 0 ]]; then
  CMD+=(--dry-run)
fi
"${CMD[@]}"
