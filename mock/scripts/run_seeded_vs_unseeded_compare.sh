#!/usr/bin/env bash
set -euo pipefail

MOCK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$MOCK_ROOT/scripts/_kvm_startup_common.sh"

if [[ $# -lt 3 ]]; then
  echo "usage: $0 <arm64_disk_image> <ssh_key> <arm64_kernel_image> [max_seconds] [output_base]" >&2
  exit 1
fi

DISK_IMG="$1"
SSH_KEY="$2"
KERNEL_IMG="$3"
MAX_SECONDS="${4:-600}"
OUTPUT_BASE="${5:-$MOCK_ROOT/output-compare}"
SYZ_DIR="$(default_syz_dir)"
SEED_WORKDIR="$OUTPUT_BASE/seed_workdir"
UNSEEDED_DIR="$OUTPUT_BASE/unseeded"
SEEDED_DIR="$OUTPUT_BASE/seeded"
COMPARISON_DIR="$OUTPUT_BASE/comparison"
UNSEEDED_METRICS_JSON="$COMPARISON_DIR/unseeded_metrics.json"
SEEDED_METRICS_JSON="$COMPARISON_DIR/seeded_metrics.json"
DELTA_JSON="$COMPARISON_DIR/delta.json"
REPORT_TXT="$COMPARISON_DIR/report.txt"
METRICS_TOOL="$MOCK_ROOT/tools/corpus_prefix_metrics.py"

mkdir -p "$OUTPUT_BASE"
rm -rf "$SEED_WORKDIR" "$UNSEEDED_DIR" "$SEEDED_DIR" "$COMPARISON_DIR"
mkdir -p "$COMPARISON_DIR"

echo "Preparing seeded input artifacts..."
cd "$MOCK_ROOT"
bash scripts/prepare_kvm_seed.sh "$SEED_WORKDIR"

bash "$MOCK_ROOT/scripts/check_kvm_fuzz_prereqs.sh" \
  --seed-workdir "$SEED_WORKDIR" \
  --syz-dir "$SYZ_DIR" \
  "$DISK_IMG" \
  "$SSH_KEY" \
  "$KERNEL_IMG"

run_fuzzer() {
  local output_dir="$1"
  shift
  cd "$MOCK_ROOT"
  cargo run --release -p healer_fuzzer --bin healer -- \
    --arch arm64 \
    -d "$DISK_IMG" \
    --ssh-key "$SSH_KEY" \
    -k "$KERNEL_IMG" \
    -S "$SYZ_DIR" \
    -o "$output_dir" \
    --max-seconds "$MAX_SECONDS" \
    "$@"
}

echo "Running unseeded arm64 KVM fuzzing..."
run_fuzzer "$UNSEEDED_DIR"

echo "Running seeded arm64 KVM fuzzing..."
run_fuzzer \
  "$SEEDED_DIR" \
  --bridge-bias "$SEED_WORKDIR/bias.json" \
  -i "$SEED_WORKDIR/input" \
  -R "$SEED_WORKDIR/relations/bridge_seed.relations"

echo "Computing comparison artifacts..."
cd "$MOCK_ROOT"
python3 "$METRICS_TOOL" "$UNSEEDED_DIR" --json >"$UNSEEDED_METRICS_JSON"
python3 "$METRICS_TOOL" "$SEEDED_DIR" --json >"$SEEDED_METRICS_JSON"
python3 "$METRICS_TOOL" "$UNSEEDED_DIR" "$SEEDED_DIR" >"$REPORT_TXT"

COMPARE_JSON="$(mktemp)"
python3 "$METRICS_TOOL" "$UNSEEDED_DIR" "$SEEDED_DIR" --json >"$COMPARE_JSON"
python3 - "$COMPARE_JSON" "$DELTA_JSON" <<'PY'
import json
import sys
from pathlib import Path

compare_json = Path(sys.argv[1])
delta_json = Path(sys.argv[2])
payload = json.loads(compare_json.read_text(encoding="utf-8"))
delta_json.write_text(json.dumps(payload["compare"], indent=2) + "\n", encoding="utf-8")
PY
rm -f "$COMPARE_JSON"

echo
echo "Seeded vs unseeded comparison complete."
echo "  unseeded output : $UNSEEDED_DIR"
echo "  seeded output   : $SEEDED_DIR"
echo "  report          : $REPORT_TXT"
echo "  unseeded json   : $UNSEEDED_METRICS_JSON"
echo "  seeded json     : $SEEDED_METRICS_JSON"
echo "  delta json      : $DELTA_JSON"
