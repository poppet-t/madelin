#!/usr/bin/env bash

if [[ -z "${MOCK_ROOT:-}" ]]; then
  MOCK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

note() {
  printf 'note: %s\n' "$*" >&2
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

require_file() {
  local path="$1"
  local message="$2"
  [[ -f "$path" ]] || die "$message"
}

require_dir() {
  local path="$1"
  local message="$2"
  [[ -d "$path" ]] || die "$message"
}

default_bridge_root() {
  if [[ -n "${BRIDGE_ROOT:-}" ]]; then
    printf '%s\n' "$BRIDGE_ROOT"
    return 0
  fi

  printf '%s\n' "$(cd "$MOCK_ROOT/.." && pwd)/uaf-bridge"
}

default_syz_dir() {
  if [[ -n "${SYZ_DIR:-}" ]]; then
    printf '%s\n' "$SYZ_DIR"
    return 0
  fi

  local candidates=(
    "$MOCK_ROOT/target/release/syz-bin"
    "$MOCK_ROOT/target/debug/syz-bin"
  )
  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -d "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  printf '%s\n' "$MOCK_ROOT/target/release/syz-bin"
}

resolve_syz_tool() {
  local syz_dir="$1"
  local tool_name="$2"
  local candidates=(
    "$syz_dir/bin/$tool_name"
    "$syz_dir/$tool_name"
  )
  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -f "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

resolve_syz_executor() {
  local syz_dir="$1"
  local os_name="${2:-linux}"
  local arch_name="${3:-arm64}"
  local target_dir="${os_name}_${arch_name}"
  local candidates=(
    "$syz_dir/bin/$target_dir/syz-executor"
    "$syz_dir/$target_dir/syz-executor"
  )
  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -f "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

require_syz_layout() {
  local syz_dir="$1"
  local os_name="${2:-linux}"
  local arch_name="${3:-arm64}"
  [[ -d "$syz_dir" ]] || die "bad syz-dir: $syz_dir"

  local syz_executor=""
  syz_executor="$(resolve_syz_executor "$syz_dir" "$os_name" "$arch_name")" || die \
    "missing syz-executor for ${os_name}/${arch_name} under $syz_dir. Checked $syz_dir/bin/${os_name}_${arch_name}/syz-executor and $syz_dir/${os_name}_${arch_name}/syz-executor"

  local syz_symbolize=""
  syz_symbolize="$(resolve_syz_tool "$syz_dir" "syz-symbolize")" || die \
    "missing syz-symbolize under $syz_dir. Checked $syz_dir/bin/syz-symbolize and $syz_dir/syz-symbolize"

  local syz_repro=""
  syz_repro="$(resolve_syz_tool "$syz_dir" "syz-repro")" || die \
    "missing syz-repro under $syz_dir. Checked $syz_dir/bin/syz-repro and $syz_dir/syz-repro"

  printf '%s\n' "$syz_executor"
}

check_model_manager_status() {
  if ! command -v python3 >/dev/null 2>&1; then
    printf 'probe unavailable (python3 not found)\n'
    return 0
  fi

  python3 - <<'PY'
import socket

sock = socket.socket()
sock.settimeout(0.5)
try:
    status = "reachable" if sock.connect_ex(("127.0.0.1", 8000)) == 0 else "not reachable"
finally:
    sock.close()

print(f"{status} (optional for startup/short runs)")
PY
}

run_ssh() {
  local ssh_key="$1"
  local ssh_port="$2"
  shift 2

  ssh \
    -F /dev/null \
    -o BatchMode=yes \
    -o ConnectTimeout=5 \
    -o ConnectionAttempts=1 \
    -o ServerAliveInterval=5 \
    -o ServerAliveCountMax=1 \
    -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -i "$ssh_key" \
    -p "$ssh_port" \
    "$@"
}

run_scp() {
  local ssh_key="$1"
  local ssh_port="$2"
  shift 2

  scp \
    -F /dev/null \
    -o BatchMode=yes \
    -o ConnectTimeout=5 \
    -o ConnectionAttempts=1 \
    -o ServerAliveInterval=5 \
    -o ServerAliveCountMax=1 \
    -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -i "$ssh_key" \
    -P "$ssh_port" \
    "$@"
}
