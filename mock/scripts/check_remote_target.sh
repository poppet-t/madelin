#!/usr/bin/env bash
set -euo pipefail

MOCK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$MOCK_ROOT/scripts/_kvm_startup_common.sh"

usage() {
  cat >&2 <<'EOF'
usage: check_remote_target.sh --target-host <host> --ssh-key <path> [--ssh-user <user>] [--ssh-port <port>] [--mode harness|witness|both] [--syz-dir <path>] [--remote-dir <path>]
EOF
  exit 1
}

run_capture() {
  local __result_var="$1"
  shift

  local output=""
  set +e
  output="$("$@" 2>&1)"
  local rc=$?
  set -e
  printf -v "$__result_var" '%s' "$output"
  return "$rc"
}

status_ok() {
  printf 'ok: %s\n' "$*"
}

status_fail() {
  printf 'error: missing_runtime_capability: %s\n' "$*" >&2
  FAILURES=$((FAILURES + 1))
}

TARGET_HOST=""
SSH_KEY=""
SSH_USER="root"
SSH_PORT="22"
MODE="both"
SYZ_DIR_OVERRIDE=""
REMOTE_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
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
    --mode)
      [[ $# -ge 2 ]] || usage
      MODE="$2"
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

[[ -n "$TARGET_HOST" ]] || usage
[[ -n "$SSH_KEY" ]] || usage
[[ "$SSH_PORT" =~ ^[0-9]+$ ]] || die "ssh-port must be an integer: $SSH_PORT"
case "$MODE" in
  witness|harness|both) ;;
  *) die "unsupported mode: $MODE" ;;
esac

require_cmd ssh
require_file "$SSH_KEY" "ssh key not found: $SSH_KEY"

if [[ -z "$REMOTE_DIR" ]]; then
  REMOTE_DIR="/tmp/madelin-remote-check-$(date +%Y%m%d%H%M%S)-$$"
fi

SSH_TARGET="${SSH_USER}@${TARGET_HOST}"
FAILURES=0

printf 'Checking remote target: %s\n' "$SSH_TARGET"
printf 'Mode: %s\n' "$MODE"

remote_output=""
if run_capture remote_output run_ssh "$SSH_KEY" "$SSH_PORT" "$SSH_TARGET" true; then
  status_ok "ssh connectivity"
else
  status_fail "ssh connectivity to $SSH_TARGET failed: ${remote_output:-no output}"
fi

printf -v REMOTE_DIR_Q '%q' "$REMOTE_DIR"
if run_capture remote_output run_ssh "$SSH_KEY" "$SSH_PORT" "$SSH_TARGET" \
  "mkdir -p $REMOTE_DIR_Q && test -w $REMOTE_DIR_Q && touch $REMOTE_DIR_Q/.madelin-write-test && rm -f $REMOTE_DIR_Q/.madelin-write-test"; then
  status_ok "remote temp dir writable: $REMOTE_DIR"
else
  status_fail "remote temp dir is not writable at $REMOTE_DIR: ${remote_output:-no output}"
fi

if run_capture remote_output run_ssh "$SSH_KEY" "$SSH_PORT" "$SSH_TARGET" "dmesg >/dev/null"; then
  status_ok "remote dmesg readable"
else
  status_fail "remote dmesg is not readable: ${remote_output:-no output}"
fi

if [[ "$MODE" == "harness" || "$MODE" == "both" ]]; then
  if run_capture remote_output run_ssh "$SSH_KEY" "$SSH_PORT" "$SSH_TARGET" "command -v gcc >/dev/null"; then
    status_ok "remote gcc present for harness mode"
  else
    status_fail "remote gcc is missing for harness mode"
  fi
fi

if [[ "$MODE" == "witness" || "$MODE" == "both" ]]; then
  SYZ_DIR="${SYZ_DIR_OVERRIDE:-$(default_syz_dir)}"
  if [[ -d "$SYZ_DIR" ]]; then
    if SYZ_EXECUTOR="$(resolve_syz_executor "$SYZ_DIR" linux arm64)"; then
      status_ok "local syz-executor available for witness upload: $SYZ_EXECUTOR"
    else
      status_fail "witness mode requires local syz-executor under $SYZ_DIR"
    fi
    if SYZ_EXECPROG="$(resolve_syz_tool "$SYZ_DIR" "syz-execprog")"; then
      status_ok "local syz-execprog available for witness upload: $SYZ_EXECPROG"
    else
      status_fail "witness mode requires local syz-execprog under $SYZ_DIR"
    fi
    printf 'note: witness mode uploads local syz-executor/syz-execprog to the remote temp dir at run time.\n'
  else
    status_fail "witness mode requires --syz-dir (or SYZ_DIR) pointing at a local syzkaller tree; missing directory: $SYZ_DIR"
  fi
fi

run_capture remote_output run_ssh "$SSH_KEY" "$SSH_PORT" "$SSH_TARGET" "rm -rf $REMOTE_DIR_Q" || true

if [[ "$FAILURES" -ne 0 ]]; then
  printf 'Remote target preflight failed with %s issue(s).\n' "$FAILURES" >&2
  exit 1
fi

printf 'Remote target preflight looks good.\n'
