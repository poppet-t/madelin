#!/usr/bin/env bash
set -euo pipefail

MOCK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$MOCK_ROOT/scripts/_kvm_startup_common.sh"

usage() {
  cat >&2 <<'EOF'
usage: run_kvm_seed_fuzz.sh [--dry-run] [--max-seconds <n>] [--seed-workdir <path>] [--output-dir <path>] [--syz-dir <path>] <arm64_disk_image> <ssh_key> <arm64_kernel_image>
EOF
  exit 1
}

DRY_RUN=0
MAX_SECONDS=""
SEED_WORKDIR="$MOCK_ROOT/seed_workdir"
OUTPUT_DIR="$MOCK_ROOT/output-kvm-seeded"
SYZ_DIR_OVERRIDE=""
POSITIONAL=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --max-seconds)
      [[ $# -ge 2 ]] || usage
      MAX_SECONDS="$2"
      shift 2
      ;;
    --seed-workdir)
      [[ $# -ge 2 ]] || usage
      SEED_WORKDIR="$2"
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
CHECK_SCRIPT="$MOCK_ROOT/scripts/check_kvm_fuzz_prereqs.sh"
DEBUG_SUMMARY_JSON="$OUTPUT_DIR/debug-summary.json"

require_file "$CHECK_SCRIPT" "prerequisite checker not found: $CHECK_SCRIPT"

bash "$CHECK_SCRIPT" \
  --seed-workdir "$SEED_WORKDIR" \
  --syz-dir "$SYZ_DIR" \
  "$DISK_IMG" \
  "$SSH_KEY" \
  "$KERNEL_IMG"

CMD=(
  cargo run --release -p healer_fuzzer --bin healer --
  --arch arm64
  --bridge-bias "$SEED_WORKDIR/bias.json"
  -d "$DISK_IMG"
  --ssh-key "$SSH_KEY"
  -k "$KERNEL_IMG"
  -S "$SYZ_DIR"
  -i "$SEED_WORKDIR/input"
  -R "$SEED_WORKDIR/relations/bridge_seed.relations"
  -o "$OUTPUT_DIR"
)

if [[ -n "$MAX_SECONDS" ]]; then
  CMD+=(--max-seconds "$MAX_SECONDS")
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  CMD+=(--dry-run --debug-summary-json "$DEBUG_SUMMARY_JSON")
fi

cd "$MOCK_ROOT"
"${CMD[@]}"

if [[ "$DRY_RUN" -eq 1 ]]; then
  printf 'Dry-run summary written to: %s\n' "$DEBUG_SUMMARY_JSON"
fi
