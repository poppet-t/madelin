#!/usr/bin/env bash
set -euo pipefail

MOCK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$MOCK_ROOT/scripts/_kvm_startup_common.sh"

usage() {
  cat >&2 <<'EOF'
usage: run_harness.sh --harness <path> --candidate <path> --target-host <host> --ssh-key <path> [--ssh-user <user>] [--ssh-port <port>] [--timing-range <csv>] [--runs-per-timing <n>] [--output-dir <path>] [--remote-dir <path>] [--dry-run]
EOF
  exit 1
}

run_logged() {
  local stdout_log="$1"
  local stderr_log="$2"
  shift 2

  set +e
  "$@" >"$stdout_log" 2>"$stderr_log"
  local rc=$?
  set -e
  return "$rc"
}

looks_like_crash_log() {
  local path="$1"
  [[ -s "$path" ]] || return 1
  grep -Eiq 'BUG: KASAN:|KASAN:|BUG: unable to handle kernel|kernel BUG at|panic:|Call trace:' "$path"
}

parse_bool_marker() {
  local marker_name="$1"
  local path="$2"
  if grep -Fq "HARNESS: ${marker_name}=1" "$path"; then
    printf '1\n'
  else
    printf '0\n'
  fi
}

HARNESS=""
CANDIDATE=""
TARGET_HOST=""
SSH_KEY=""
SSH_USER="root"
SSH_PORT="22"
TIMING_RANGE="0,100,1000,5000,10000,50000"
RUNS_PER_TIMING="10"
OUTPUT_DIR="$MOCK_ROOT/output-harness"
REMOTE_DIR=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --harness)
      [[ $# -ge 2 ]] || usage
      HARNESS="$2"
      shift 2
      ;;
    --candidate)
      [[ $# -ge 2 ]] || usage
      CANDIDATE="$2"
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
    --timing-range)
      [[ $# -ge 2 ]] || usage
      TIMING_RANGE="$2"
      shift 2
      ;;
    --runs-per-timing)
      [[ $# -ge 2 ]] || usage
      RUNS_PER_TIMING="$2"
      shift 2
      ;;
    --output-dir)
      [[ $# -ge 2 ]] || usage
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --remote-dir)
      [[ $# -ge 2 ]] || usage
      REMOTE_DIR="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      ;;
    --*)
      die "unknown option: $1"
      ;;
    *)
      usage
      ;;
  esac
done

[[ -n "$HARNESS" ]] || usage
[[ -n "$CANDIDATE" ]] || usage
[[ -n "$TARGET_HOST" ]] || usage
[[ -n "$SSH_KEY" ]] || usage
[[ "$SSH_PORT" =~ ^[0-9]+$ ]] || die "ssh-port must be an integer: $SSH_PORT"
[[ "$RUNS_PER_TIMING" =~ ^[1-9][0-9]*$ ]] || die "runs-per-timing must be a positive integer: $RUNS_PER_TIMING"

require_cmd ssh
require_cmd scp
require_cmd python3
require_file "$HARNESS" "harness source not found: $HARNESS"
require_file "$CANDIDATE" "candidate file not found: $CANDIDATE"
require_file "$SSH_KEY" "ssh key not found: $SSH_KEY"

IFS=',' read -r -a TIMINGS <<<"$TIMING_RANGE"
[[ ${#TIMINGS[@]} -gt 0 ]] || die "timing-range must include at least one timing"
for timing in "${TIMINGS[@]}"; do
  [[ "$timing" =~ ^[0-9]+$ ]] || die "timing-range contains non-integer value: $timing"
done

if [[ -z "$REMOTE_DIR" ]]; then
  REMOTE_DIR="/tmp/madelin-harness-$(date +%Y%m%d%H%M%S)-$$"
fi

SSH_TARGET="${SSH_USER}@${TARGET_HOST}"
LOG_DIR="$OUTPUT_DIR/logs"
BUILD_LOG_DIR="$LOG_DIR/build"
RUNS_DIR="$OUTPUT_DIR/runs"
CRASH_RAW_DIR="$OUTPUT_DIR/crashes/raw_logs"
mkdir -p "$LOG_DIR" "$BUILD_LOG_DIR" "$RUNS_DIR" "$CRASH_RAW_DIR"

if [[ "$DRY_RUN" -eq 1 ]]; then
  bash "$MOCK_ROOT/scripts/build_harness.sh" \
    --harness "$HARNESS" \
    --target-host "$TARGET_HOST" \
    --ssh-key "$SSH_KEY" \
    --ssh-user "$SSH_USER" \
    --ssh-port "$SSH_PORT" \
    --remote-dir "$REMOTE_DIR" \
    --log-dir "$BUILD_LOG_DIR" \
    --dry-run >/dev/null
  printf 'Dry-run harness execution plan:\n'
  printf '  target: %s\n' "$SSH_TARGET"
  printf '  harness: %s\n' "$HARNESS"
  printf '  candidate: %s\n' "$CANDIDATE"
  printf '  remote dir: %s\n' "$REMOTE_DIR"
  printf '  runs per timing: %s\n' "$RUNS_PER_TIMING"
  printf '  timings: %s\n' "$TIMING_RANGE"
  printf '  output dir: %s\n' "$OUTPUT_DIR"
  exit 0
fi

REMOTE_BINARY="$(bash "$MOCK_ROOT/scripts/build_harness.sh" \
  --harness "$HARNESS" \
  --target-host "$TARGET_HOST" \
  --ssh-key "$SSH_KEY" \
  --ssh-user "$SSH_USER" \
  --ssh-port "$SSH_PORT" \
  --remote-dir "$REMOTE_DIR" \
  --log-dir "$BUILD_LOG_DIR")"

RUN_STARTED_AT="$(date +%s)"

for timing in "${TIMINGS[@]}"; do
  TIMING_LABEL="${timing}us"
  for run_index in $(seq 1 "$RUNS_PER_TIMING"); do
    RUN_DIR="$RUNS_DIR/$TIMING_LABEL/run-$run_index"
    mkdir -p "$RUN_DIR"

    STDOUT_LOG="$RUN_DIR/stdout.log"
    STDERR_LOG="$RUN_DIR/stderr.log"
    DMESG_BEFORE_LOG="$RUN_DIR/dmesg-before.log"
    DMESG_AFTER_LOG="$RUN_DIR/dmesg-after.log"
    DMESG_DELTA_LOG="$RUN_DIR/dmesg-delta.log"
    RESULT_JSON="$RUN_DIR/result.json"
    RUN_LOG_PREFIX="$LOG_DIR/${TIMING_LABEL}-run-${run_index}"
    RUN_EXIT_CODE=0

    if ! run_logged "$RUN_LOG_PREFIX-dmesg-before.stdout.log" "$RUN_LOG_PREFIX-dmesg-before.stderr.log" \
      run_ssh "$SSH_KEY" "$SSH_PORT" "$SSH_TARGET" "dmesg"; then
      : >"$DMESG_BEFORE_LOG"
      note "failed to capture pre-run dmesg for ${TIMING_LABEL} run ${run_index}"
    else
      cp "$RUN_LOG_PREFIX-dmesg-before.stdout.log" "$DMESG_BEFORE_LOG"
    fi

    set +e
    run_ssh "$SSH_KEY" "$SSH_PORT" "$SSH_TARGET" "$REMOTE_BINARY" "$timing" >"$STDOUT_LOG" 2>"$STDERR_LOG"
    RUN_EXIT_CODE=$?
    set -e

    if ! run_logged "$RUN_LOG_PREFIX-dmesg-after.stdout.log" "$RUN_LOG_PREFIX-dmesg-after.stderr.log" \
      run_ssh "$SSH_KEY" "$SSH_PORT" "$SSH_TARGET" "dmesg"; then
      : >"$DMESG_AFTER_LOG"
      note "failed to capture post-run dmesg for ${TIMING_LABEL} run ${run_index}"
    else
      cp "$RUN_LOG_PREFIX-dmesg-after.stdout.log" "$DMESG_AFTER_LOG"
    fi

    if [[ -f "$DMESG_BEFORE_LOG" && -f "$DMESG_AFTER_LOG" ]]; then
      BEFORE_LINES="$(wc -l < "$DMESG_BEFORE_LOG")"
      tail -n "+$((BEFORE_LINES + 1))" "$DMESG_AFTER_LOG" >"$DMESG_DELTA_LOG" || cp "$DMESG_AFTER_LOG" "$DMESG_DELTA_LOG"
    else
      : >"$DMESG_DELTA_LOG"
    fi

    PRIMARY_CRASH_LOG=""
    for candidate_log in "$DMESG_DELTA_LOG" "$STDERR_LOG" "$STDOUT_LOG"; do
      if looks_like_crash_log "$candidate_log"; then
        PRIMARY_CRASH_LOG="$CRASH_RAW_DIR/${TIMING_LABEL}-run-${run_index}-$(basename "$candidate_log")"
        cp "$candidate_log" "$PRIMARY_CRASH_LOG"
        break
      fi
    done

    SETUP_FAILED_RUN="$(parse_bool_marker "setup_failed" "$STDOUT_LOG")"
    CANDIDATE_REACHED_RUN="$(parse_bool_marker "candidate_reached" "$STDOUT_LOG")"
    TIMING_WINDOW_RUN="$(parse_bool_marker "timing_window_entered" "$STDOUT_LOG")"
    EXECUTION_COMPLETED_RUN="$(parse_bool_marker "execution_completed" "$STDOUT_LOG")"

    RESULT_JSON="$RESULT_JSON" \
    TIMING_US="$timing" \
    RUN_INDEX="$run_index" \
    RUN_EXIT_CODE="$RUN_EXIT_CODE" \
    SETUP_FAILED_RUN="$SETUP_FAILED_RUN" \
    CANDIDATE_REACHED_RUN="$CANDIDATE_REACHED_RUN" \
    TIMING_WINDOW_RUN="$TIMING_WINDOW_RUN" \
    EXECUTION_COMPLETED_RUN="$EXECUTION_COMPLETED_RUN" \
    STDOUT_LOG="$STDOUT_LOG" \
    STDERR_LOG="$STDERR_LOG" \
    DMESG_BEFORE_LOG="$DMESG_BEFORE_LOG" \
    DMESG_AFTER_LOG="$DMESG_AFTER_LOG" \
    DMESG_DELTA_LOG="$DMESG_DELTA_LOG" \
    PRIMARY_CRASH_LOG="$PRIMARY_CRASH_LOG" \
    python3 - <<'PY'
import json
import os
from pathlib import Path

payload = {
    "timing_us": int(os.environ["TIMING_US"]),
    "run_index": int(os.environ["RUN_INDEX"]),
    "exit_code": int(os.environ["RUN_EXIT_CODE"]),
    "setup_failed": os.environ["SETUP_FAILED_RUN"] == "1",
    "candidate_reached": os.environ["CANDIDATE_REACHED_RUN"] == "1",
    "timing_window_entered": os.environ["TIMING_WINDOW_RUN"] == "1",
    "execution_completed": os.environ["EXECUTION_COMPLETED_RUN"] == "1",
    "stdout_log": os.environ["STDOUT_LOG"],
    "stderr_log": os.environ["STDERR_LOG"],
    "dmesg_before_log": os.environ["DMESG_BEFORE_LOG"],
    "dmesg_after_log": os.environ["DMESG_AFTER_LOG"],
    "dmesg_delta_log": os.environ["DMESG_DELTA_LOG"],
    "crash_log": os.environ["PRIMARY_CRASH_LOG"] or None,
}
path = Path(os.environ["RESULT_JSON"])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  done
done

RUN_FINISHED_AT="$(date +%s)"
WALL_SECONDS="$((RUN_FINISHED_AT - RUN_STARTED_AT))"

python3 -m verdict.aggregate \
  --output-dir "$OUTPUT_DIR" \
  --candidate "$CANDIDATE" \
  --wall-seconds "$WALL_SECONDS" \
  --execution-mode harness_timing_sweep \
  --remote-host "$TARGET_HOST" \
  --harness-source "$HARNESS"

printf 'Harness output directory: %s\n' "$OUTPUT_DIR"
printf 'Remote artifact directory: %s\n' "$REMOTE_DIR"
