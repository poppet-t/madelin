#!/usr/bin/env bash
set -euo pipefail

MOCK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$MOCK_ROOT/scripts/_kvm_startup_common.sh"

usage() {
  cat >&2 <<'EOF'
usage: build_harness.sh --harness <path> --target-host <host> --ssh-key <path> [--ssh-user <user>] [--ssh-port <port>] [--remote-dir <path>] [--binary-name <name>] [--log-dir <path>] [--dry-run]
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

HARNESS=""
TARGET_HOST=""
SSH_KEY=""
SSH_USER="root"
SSH_PORT="22"
REMOTE_DIR=""
BINARY_NAME="harness_runner"
LOG_DIR=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --harness)
      [[ $# -ge 2 ]] || usage
      HARNESS="$2"
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
    --remote-dir)
      [[ $# -ge 2 ]] || usage
      REMOTE_DIR="$2"
      shift 2
      ;;
    --binary-name)
      [[ $# -ge 2 ]] || usage
      BINARY_NAME="$2"
      shift 2
      ;;
    --log-dir)
      [[ $# -ge 2 ]] || usage
      LOG_DIR="$2"
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
[[ -n "$TARGET_HOST" ]] || usage
[[ -n "$SSH_KEY" ]] || usage
[[ "$SSH_PORT" =~ ^[0-9]+$ ]] || die "ssh-port must be an integer: $SSH_PORT"

require_cmd ssh
require_cmd scp
require_file "$HARNESS" "harness source not found: $HARNESS"
require_file "$SSH_KEY" "ssh key not found: $SSH_KEY"

if [[ -z "$REMOTE_DIR" ]]; then
  REMOTE_DIR="/tmp/madelin-harness-build-$(date +%Y%m%d%H%M%S)-$$"
fi
if [[ -z "$LOG_DIR" ]]; then
  LOG_DIR="$MOCK_ROOT/output-harness-build/logs"
fi
mkdir -p "$LOG_DIR"

SSH_TARGET="${SSH_USER}@${TARGET_HOST}"
REMOTE_SOURCE="$REMOTE_DIR/harness.c"
REMOTE_BINARY="$REMOTE_DIR/$BINARY_NAME"

printf -v REMOTE_DIR_Q '%q' "$REMOTE_DIR"
printf -v REMOTE_SOURCE_Q '%q' "$REMOTE_SOURCE"
printf -v REMOTE_BINARY_Q '%q' "$REMOTE_BINARY"

if [[ "$DRY_RUN" -eq 1 ]]; then
  printf 'Dry-run harness build plan:\n'
  printf '  target: %s\n' "$SSH_TARGET"
  printf '  harness: %s\n' "$HARNESS"
  printf '  remote dir: %s\n' "$REMOTE_DIR"
  printf '  remote source: %s\n' "$REMOTE_SOURCE"
  printf '  remote binary: %s\n' "$REMOTE_BINARY"
  printf '%s\n' "$REMOTE_BINARY"
  exit 0
fi

if ! run_logged "$LOG_DIR/remote-mkdir.stdout.log" "$LOG_DIR/remote-mkdir.stderr.log" \
  run_ssh "$SSH_KEY" "$SSH_PORT" "$SSH_TARGET" "mkdir -p $REMOTE_DIR_Q"; then
  die "failed to create remote build directory: $REMOTE_DIR"
fi

if ! run_logged "$LOG_DIR/scp-harness.stdout.log" "$LOG_DIR/scp-harness.stderr.log" \
  run_scp "$SSH_KEY" "$SSH_PORT" "$HARNESS" "${SSH_TARGET}:$REMOTE_SOURCE"; then
  die "failed to copy harness source to $SSH_TARGET"
fi

if ! run_logged "$LOG_DIR/remote-compile.stdout.log" "$LOG_DIR/remote-compile.stderr.log" \
  run_ssh "$SSH_KEY" "$SSH_PORT" "$SSH_TARGET" \
    "gcc -O2 -pthread -Wall -Wextra -o $REMOTE_BINARY_Q $REMOTE_SOURCE_Q"; then
  die "missing runtime capability: remote harness compile failed (check gcc and kernel headers on the target); see $LOG_DIR/remote-compile.stderr.log or run scripts/check_remote_target.sh --mode harness"
fi

printf '%s\n' "$REMOTE_BINARY"
