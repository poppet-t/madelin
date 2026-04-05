#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage: stage_arm64_guest_tooling.sh \
  --ssh-key <path> \
  [--ssh-port <port>] \
  [--guest-syz-execprog-path <path>] \
  [--guest-syz-executor-path <path>] \
  [--out-dir <path>]

Copies real linux/arm64 syzkaller tooling out of a reachable guest,
validates the ELF architecture on the host, and emits a small manifest.
USAGE
  exit 2
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

SSH_KEY=""
SSH_PORT=10022
OUT_DIR=""
GUEST_SYZ_EXECPROG_PATH="/root/syz-execprog"
GUEST_SYZ_EXECUTOR_PATH="/root/syz-executor"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ssh-key) SSH_KEY="${2:-}"; shift 2 ;;
    --ssh-port) SSH_PORT="${2:-}"; shift 2 ;;
    --out-dir) OUT_DIR="${2:-}"; shift 2 ;;
    --guest-syz-execprog-path) GUEST_SYZ_EXECPROG_PATH="${2:-}"; shift 2 ;;
    --guest-syz-executor-path) GUEST_SYZ_EXECUTOR_PATH="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown argument: $1" >&2; usage ;;
  esac
done

[[ -n "$SSH_KEY" ]] || usage
[[ -f "$SSH_KEY" ]] || { echo "Missing SSH key: $SSH_KEY" >&2; exit 1; }
if [[ -z "$OUT_DIR" ]]; then
  OUT_DIR="$(pwd)/out/net-runtime/guest-tools/linux-arm64"
fi

require_cmd ssh
require_cmd scp
require_cmd python3

mkdir -p "$OUT_DIR"

SSH_BASE=(
  ssh
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
  -o BatchMode=yes
  -o ConnectTimeout=10
  -i "$SSH_KEY"
  -p "$SSH_PORT"
  root@127.0.0.1
)
SCP_BASE=(
  scp
  -O
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
  -o BatchMode=yes
  -o ConnectTimeout=10
  -i "$SSH_KEY"
  -P "$SSH_PORT"
)

"${SSH_BASE[@]}" true >/dev/null

copy_one() {
  local remote_path="$1"
  local local_path="$2"
  "${SCP_BASE[@]}" "root@127.0.0.1:${remote_path}" "$local_path"
  chmod +x "$local_path"
  python3 - <<'PY' "$local_path"
import pathlib
import struct
import sys

path = pathlib.Path(sys.argv[1])
data = path.read_bytes()[:64]
if len(data) < 20 or data[:4] != b"\x7fELF":
    raise SystemExit(f"{path} is not an ELF binary")
endian = "<" if data[5] == 1 else ">" if data[5] == 2 else None
if endian is None:
    raise SystemExit(f"{path} has an unreadable ELF header")
machine = struct.unpack(f"{endian}H", data[18:20])[0]
if machine != 183:
    raise SystemExit(f"{path} is not linux/arm64 (e_machine={machine})")
print(machine)
PY
}

copy_one "$GUEST_SYZ_EXECPROG_PATH" "$OUT_DIR/syz-execprog"
copy_one "$GUEST_SYZ_EXECUTOR_PATH" "$OUT_DIR/syz-executor"

python3 - <<'PY' "$OUT_DIR" "$SSH_PORT" "$GUEST_SYZ_EXECPROG_PATH" "$GUEST_SYZ_EXECUTOR_PATH"
import json
import pathlib
import sys

out_dir = pathlib.Path(sys.argv[1])
manifest = {
    "ssh_port": int(sys.argv[2]),
    "guest_syz_execprog_path": sys.argv[3],
    "guest_syz_executor_path": sys.argv[4],
    "artifacts": {
        "syz_execprog": str(out_dir / "syz-execprog"),
        "syz_executor": str(out_dir / "syz-executor"),
    },
}
(out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(json.dumps(manifest, indent=2))
PY
