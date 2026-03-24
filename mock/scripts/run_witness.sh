#!/usr/bin/env bash
set -euo pipefail

MOCK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$MOCK_ROOT/scripts/_kvm_startup_common.sh"

usage() {
  cat >&2 <<'EOF'
usage: run_witness.sh --witness <path> --candidate <path> --target-host <host> --ssh-key <path> [--ssh-user <user>] [--ssh-port <port>] [--runs <n>] [--output-dir <path>] [--syz-dir <path>] [--remote-dir <path>] [--dry-run]
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

copy_remote_artifact() {
  local remote_path="$1"
  local local_path="$2"

  mkdir -p "$(dirname "$local_path")"
  set +e
  run_scp "$SSH_KEY" "$SSH_PORT" "${SSH_TARGET}:$remote_path" "$local_path" >/dev/null 2>"$local_path.copy.stderr.log"
  local rc=$?
  set -e
  return "$rc"
}

copy_if_crash_log() {
  local src="$1"
  local dest_name="$2"

  if looks_like_crash_log "$src"; then
    mkdir -p "$CRASH_RAW_DIR"
    cp "$src" "$CRASH_RAW_DIR/$dest_name"
    CRASH_LOGS_FOUND=$((CRASH_LOGS_FOUND + 1))
    return 0
  fi
  return 1
}

WITNESS=""
CANDIDATE=""
TARGET_HOST=""
SSH_KEY=""
SSH_USER="root"
SSH_PORT="22"
RUNS="5"
OUTPUT_DIR="$MOCK_ROOT/output-witness"
SYZ_DIR_OVERRIDE=""
REMOTE_DIR=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --witness)
      [[ $# -ge 2 ]] || usage
      WITNESS="$2"
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
    --runs)
      [[ $# -ge 2 ]] || usage
      RUNS="$2"
      shift 2
      ;;
    --output-dir)
      [[ $# -ge 2 ]] || usage
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --syz-dir)
      [[ $# -ge 2 ]] || usage
      SYZ_DIR_OVERRIDE="$2"
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

[[ -n "$WITNESS" ]] || usage
[[ -n "$CANDIDATE" ]] || usage
[[ -n "$TARGET_HOST" ]] || usage
[[ -n "$SSH_KEY" ]] || usage
[[ "$RUNS" =~ ^[1-9][0-9]*$ ]] || die "runs must be a positive integer: $RUNS"
[[ "$SSH_PORT" =~ ^[0-9]+$ ]] || die "ssh-port must be an integer: $SSH_PORT"

require_cmd ssh
require_cmd scp
require_file "$WITNESS" "witness file not found: $WITNESS"
require_file "$CANDIDATE" "candidate file not found: $CANDIDATE"
require_file "$SSH_KEY" "ssh key not found: $SSH_KEY"

SYZ_DIR="${SYZ_DIR_OVERRIDE:-$(default_syz_dir)}"
require_dir "$SYZ_DIR" "bad syz-dir: $SYZ_DIR"

SYZ_EXECUTOR="$(resolve_syz_executor "$SYZ_DIR" linux arm64)" || die \
  "missing syz-executor for linux/arm64 under $SYZ_DIR"
SYZ_EXECPROG="$(resolve_syz_tool "$SYZ_DIR" "syz-execprog")" || die \
  "missing syz-execprog under $SYZ_DIR. Checked $SYZ_DIR/bin/syz-execprog and $SYZ_DIR/syz-execprog"

if [[ -z "$REMOTE_DIR" ]]; then
  REMOTE_DIR="/tmp/madelin-witness-$(date +%Y%m%d%H%M%S)-$$"
fi

SSH_TARGET="${SSH_USER}@${TARGET_HOST}"
LOG_DIR="$OUTPUT_DIR/logs"
CRASH_RAW_DIR="$OUTPUT_DIR/crashes/raw_logs"
REMOTE_WITNESS="$REMOTE_DIR/witness.syz"
REMOTE_EXECUTOR="$REMOTE_DIR/syz-executor"
REMOTE_EXECPROG="$REMOTE_DIR/syz-execprog"
REMOTE_DMESG_BEFORE="$REMOTE_DIR/dmesg-before.log"
REMOTE_DMESG_AFTER="$REMOTE_DIR/dmesg-after.log"
REMOTE_STDOUT="$REMOTE_DIR/execprog.stdout.log"
REMOTE_STDERR="$REMOTE_DIR/execprog.stderr.log"
REMOTE_RUN_METADATA="$REMOTE_DIR/run-metadata.env"
EXEC_STDOUT_LOG="$LOG_DIR/execprog.stdout.log"
EXEC_STDERR_LOG="$LOG_DIR/execprog.stderr.log"
DMESG_BEFORE_LOG="$LOG_DIR/remote-dmesg-before.log"
DMESG_AFTER_LOG="$LOG_DIR/remote-dmesg-after.log"
DMESG_DELTA_LOG="$LOG_DIR/remote-dmesg-delta.log"
RUN_METADATA_LOG="$LOG_DIR/run-metadata.env"

mkdir -p "$LOG_DIR"

printf -v REMOTE_DIR_Q '%q' "$REMOTE_DIR"
printf -v REMOTE_DMESG_BEFORE_Q '%q' "$REMOTE_DMESG_BEFORE"
printf -v REMOTE_DMESG_AFTER_Q '%q' "$REMOTE_DMESG_AFTER"

if [[ "$DRY_RUN" -eq 1 ]]; then
  printf 'Dry-run witness execution plan:\n'
  printf '  target: %s\n' "$SSH_TARGET"
  printf '  witness: %s\n' "$WITNESS"
  printf '  candidate: %s\n' "$CANDIDATE"
  printf '  syz-execprog: %s\n' "$SYZ_EXECPROG"
  printf '  syz-executor: %s\n' "$SYZ_EXECUTOR"
  printf '  remote dir: %s\n' "$REMOTE_DIR"
  printf '  output dir: %s\n' "$OUTPUT_DIR"
  printf '  runs: %s\n' "$RUNS"
  exit 0
fi

SETUP_FAILED=0
FAILURE_REASON=""

if ! run_logged "$LOG_DIR/remote-mkdir.stdout.log" "$LOG_DIR/remote-mkdir.stderr.log" \
  run_ssh "$SSH_KEY" "$SSH_PORT" "$SSH_TARGET" "mkdir -p $REMOTE_DIR_Q"; then
  SETUP_FAILED=1
  FAILURE_REASON="failed to create remote directory $REMOTE_DIR"
fi

if [[ "$SETUP_FAILED" -eq 0 ]]; then
  if ! run_logged "$LOG_DIR/scp-witness.stdout.log" "$LOG_DIR/scp-witness.stderr.log" \
    run_scp "$SSH_KEY" "$SSH_PORT" "$WITNESS" "${SSH_TARGET}:$REMOTE_WITNESS"; then
    SETUP_FAILED=1
    FAILURE_REASON="failed to copy witness to $SSH_TARGET"
  fi
fi

if [[ "$SETUP_FAILED" -eq 0 ]]; then
  if ! run_logged "$LOG_DIR/scp-executor.stdout.log" "$LOG_DIR/scp-executor.stderr.log" \
    run_scp "$SSH_KEY" "$SSH_PORT" "$SYZ_EXECUTOR" "${SSH_TARGET}:$REMOTE_EXECUTOR"; then
    SETUP_FAILED=1
    FAILURE_REASON="failed to copy syz-executor to $SSH_TARGET"
  fi
fi

if [[ "$SETUP_FAILED" -eq 0 ]]; then
  if ! run_logged "$LOG_DIR/scp-execprog.stdout.log" "$LOG_DIR/scp-execprog.stderr.log" \
    run_scp "$SSH_KEY" "$SSH_PORT" "$SYZ_EXECPROG" "${SSH_TARGET}:$REMOTE_EXECPROG"; then
    SETUP_FAILED=1
    FAILURE_REASON="failed to copy syz-execprog to $SSH_TARGET"
  fi
fi

if [[ "$SETUP_FAILED" -eq 0 ]]; then
  if ! run_logged "$LOG_DIR/dmesg-before.stdout.log" "$LOG_DIR/dmesg-before.stderr.log" \
    run_ssh "$SSH_KEY" "$SSH_PORT" "$SSH_TARGET" "dmesg > $REMOTE_DMESG_BEFORE_Q"; then
    note "failed to capture pre-run dmesg; continuing"
  fi
fi

RUN_STARTED_AT="$(date +%s)"
REMOTE_RUN_STATUS=0

if [[ "$SETUP_FAILED" -eq 0 ]]; then
  set +e
  run_ssh "$SSH_KEY" "$SSH_PORT" "$SSH_TARGET" bash -s -- "$REMOTE_DIR" "$RUNS" >"$LOG_DIR/remote-run.stdout.log" 2>"$LOG_DIR/remote-run.stderr.log" <<'EOF'
set -euo pipefail

REMOTE_DIR="$1"
RUNS="$2"

cd "$REMOTE_DIR"
chmod +x ./syz-executor ./syz-execprog

: > execprog.stdout.log
: > execprog.stderr.log

attempted_runs=0
successful_runs=0
failed_runs=0
run_idx=1
while [[ "$run_idx" -le "$RUNS" ]]; do
  attempted_runs=$((attempted_runs + 1))
  printf '=== run %s ===\n' "$run_idx" >> execprog.stdout.log
  if ./syz-execprog -executor=./syz-executor -repeat=1 -procs=1 -threaded=1 ./witness.syz >>execprog.stdout.log 2>>execprog.stderr.log; then
    successful_runs=$((successful_runs + 1))
  else
    failed_runs=$((failed_runs + 1))
  fi
  case $((run_idx % 3)) in
    1) sleep 0.05 ;;
    2) sleep 0.2 ;;
    *) : ;;
  esac
  run_idx=$((run_idx + 1))
done

{
  printf 'attempted_runs=%s\n' "$attempted_runs"
  printf 'successful_runs=%s\n' "$successful_runs"
  printf 'failed_runs=%s\n' "$failed_runs"
} > run-metadata.env
EOF
  REMOTE_RUN_STATUS=$?
  set -e
fi

RUN_FINISHED_AT="$(date +%s)"
WALL_SECONDS="$((RUN_FINISHED_AT - RUN_STARTED_AT))"

if [[ "$SETUP_FAILED" -eq 0 ]]; then
  if ! run_logged "$LOG_DIR/dmesg-after.stdout.log" "$LOG_DIR/dmesg-after.stderr.log" \
    run_ssh "$SSH_KEY" "$SSH_PORT" "$SSH_TARGET" "dmesg > $REMOTE_DMESG_AFTER_Q"; then
    note "failed to capture post-run dmesg"
  fi
fi

if [[ "$SETUP_FAILED" -eq 0 ]]; then
  copy_remote_artifact "$REMOTE_STDOUT" "$EXEC_STDOUT_LOG" || note "failed to copy remote exec stdout log"
  copy_remote_artifact "$REMOTE_STDERR" "$EXEC_STDERR_LOG" || note "failed to copy remote exec stderr log"
  copy_remote_artifact "$REMOTE_DMESG_BEFORE" "$DMESG_BEFORE_LOG" || note "failed to copy pre-run dmesg log"
  copy_remote_artifact "$REMOTE_DMESG_AFTER" "$DMESG_AFTER_LOG" || note "failed to copy post-run dmesg log"
  copy_remote_artifact "$REMOTE_RUN_METADATA" "$RUN_METADATA_LOG" || note "failed to copy run metadata"
fi

ATTEMPTED_RUNS=0
SUCCESSFUL_RUNS=0
FAILED_RUNS=0
if [[ -f "$RUN_METADATA_LOG" ]]; then
  while IFS='=' read -r key value; do
    case "$key" in
      attempted_runs) ATTEMPTED_RUNS="$value" ;;
      successful_runs) SUCCESSFUL_RUNS="$value" ;;
      failed_runs) FAILED_RUNS="$value" ;;
    esac
  done < "$RUN_METADATA_LOG"
fi

if [[ -f "$DMESG_AFTER_LOG" ]]; then
  if [[ -f "$DMESG_BEFORE_LOG" ]]; then
    BEFORE_LINES="$(wc -l < "$DMESG_BEFORE_LOG")"
    tail -n "+$((BEFORE_LINES + 1))" "$DMESG_AFTER_LOG" >"$DMESG_DELTA_LOG" || cp "$DMESG_AFTER_LOG" "$DMESG_DELTA_LOG"
  else
    cp "$DMESG_AFTER_LOG" "$DMESG_DELTA_LOG"
  fi
fi

CRASH_LOGS_FOUND=0
[[ -f "$DMESG_DELTA_LOG" ]] && copy_if_crash_log "$DMESG_DELTA_LOG" "witness-dmesg.log" || true
[[ -f "$EXEC_STDERR_LOG" ]] && copy_if_crash_log "$EXEC_STDERR_LOG" "witness-stderr.log" || true
[[ -f "$EXEC_STDOUT_LOG" ]] && copy_if_crash_log "$EXEC_STDOUT_LOG" "witness-stdout.log" || true

EXECUTION_COMPLETED=0
if [[ "$ATTEMPTED_RUNS" -gt 0 ]]; then
  EXECUTION_COMPLETED=1
fi

if [[ "$SETUP_FAILED" -eq 0 && "$CRASH_LOGS_FOUND" -eq 0 && "$ATTEMPTED_RUNS" -gt 0 && "$FAILED_RUNS" -eq "$ATTEMPTED_RUNS" ]]; then
  SETUP_FAILED=1
  FAILURE_REASON="every witness attempt failed before a usable crash signal was collected"
fi

if [[ "$SETUP_FAILED" -eq 0 && "$REMOTE_RUN_STATUS" -ne 0 && "$ATTEMPTED_RUNS" -eq 0 ]]; then
  SETUP_FAILED=1
  FAILURE_REASON="remote witness runner exited before recording any attempts"
fi

if [[ "$SETUP_FAILED" -eq 1 ]]; then
  note "${FAILURE_REASON:-witness setup failed}"
fi

if command -v python3 >/dev/null 2>&1; then
  VERDICT_CMD=(
    python3 -m verdict.emit_verdict
    --output-dir "$OUTPUT_DIR"
    --candidate "$CANDIDATE"
    --wall-seconds "$WALL_SECONDS"
    --runs "$ATTEMPTED_RUNS"
    --execution-mode witness_remote
    --remote-host "$TARGET_HOST"
    --witness-source "$WITNESS"
  )

  if [[ "$EXECUTION_COMPLETED" -eq 1 ]]; then
    VERDICT_CMD+=(--execution-completed --witness-run-completed)
  fi
  if [[ "$SETUP_FAILED" -eq 1 ]]; then
    VERDICT_CMD+=(--setup-failed)
  fi

  if ! "${VERDICT_CMD[@]}"; then
    note "verdict emission failed; witness logs remain available in $OUTPUT_DIR"
  fi
else
  note "python3 not found; skipping verdict emission"
fi

printf 'Witness output directory: %s\n' "$OUTPUT_DIR"
printf 'Remote artifact directory: %s\n' "$REMOTE_DIR"

if [[ "$SETUP_FAILED" -eq 1 ]]; then
  exit 1
fi
