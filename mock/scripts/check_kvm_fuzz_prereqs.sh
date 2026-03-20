#!/usr/bin/env bash
set -euo pipefail

MOCK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$MOCK_ROOT/scripts/_kvm_startup_common.sh"

usage() {
  cat >&2 <<'EOF'
usage: check_kvm_fuzz_prereqs.sh [--seed-workdir <path>] [--syz-dir <path>] <arm64_disk_image> <ssh_key> <arm64_kernel_image>
EOF
  exit 1
}

SEED_WORKDIR="$MOCK_ROOT/seed_workdir"
SYZ_DIR_OVERRIDE=""
POSITIONAL=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --seed-workdir)
      [[ $# -ge 2 ]] || usage
      SEED_WORKDIR="$2"
      shift 2
      ;;
    --syz-dir)
      [[ $# -ge 2 ]] || usage
      SYZ_DIR_OVERRIDE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      ;;
    --*)
      die "unknown option: $1"
      ;;
    *)
      POSITIONAL+=("$1")
      shift
      ;;
  esac
done

[[ ${#POSITIONAL[@]} -eq 3 ]] || usage

DISK_IMG="${POSITIONAL[0]}"
SSH_KEY="${POSITIONAL[1]}"
KERNEL_IMG="${POSITIONAL[2]}"
SYZ_DIR="${SYZ_DIR_OVERRIDE:-$(default_syz_dir)}"
BRIDGE_ROOT="$(default_bridge_root)"
SEED_INPUT_DIR="$SEED_WORKDIR/input"
RELATIONS_FILE="$SEED_WORKDIR/relations/bridge_seed.relations"
BIAS_FILE="$SEED_WORKDIR/bias.json"
BRIDGE_SEED="$BRIDGE_ROOT/out/uafx_kvm_mock_seed.json"

require_cmd cargo
require_file "$DISK_IMG" "disk image not found: $DISK_IMG"
require_file "$SSH_KEY" "ssh key not found: $SSH_KEY"
require_file "$KERNEL_IMG" "kernel image not found: $KERNEL_IMG"
require_dir "$SEED_INPUT_DIR" "seed input directory not found: $SEED_INPUT_DIR. Run scripts/prepare_kvm_seed.sh first."
require_file "$RELATIONS_FILE" "seed relations file not found: $RELATIONS_FILE. Run scripts/prepare_kvm_seed.sh first."
require_file "$BIAS_FILE" "bridge bias file not found: $BIAS_FILE. Run scripts/prepare_kvm_seed.sh first."

SYZ_EXECUTOR="$(require_syz_layout "$SYZ_DIR" "linux" "arm64")"

if [[ -f "$BRIDGE_SEED" ]]; then
  printf 'ok: bridge seed artifact %s\n' "$BRIDGE_SEED"
else
  note "bridge seed artifact not found at $BRIDGE_SEED. Run bash $BRIDGE_ROOT/scripts/run_end_to_end_kvm_demo.sh if you need to regenerate it."
fi

printf 'ok: cargo is available\n'
printf 'ok: disk image %s\n' "$DISK_IMG"
printf 'ok: ssh key %s\n' "$SSH_KEY"
printf 'ok: kernel image %s\n' "$KERNEL_IMG"
printf 'ok: seed input dir %s\n' "$SEED_INPUT_DIR"
printf 'ok: relations file %s\n' "$RELATIONS_FILE"
printf 'ok: bridge bias file %s\n' "$BIAS_FILE"
printf 'ok: syz-dir %s\n' "$SYZ_DIR"
printf 'ok: syz-executor %s\n' "$SYZ_EXECUTOR"
printf 'ok: model manager %s\n' "$(check_model_manager_status)"
printf 'Startup prerequisites look good.\n'
