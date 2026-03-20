#!/usr/bin/env bash
set -euo pipefail

MOCK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$MOCK_ROOT/scripts/_kvm_startup_common.sh"

BRIDGE_ROOT="$(default_bridge_root)"
SEED_OUT_DIR="${1:-$MOCK_ROOT/seed_workdir}"
SEED_JSON="$BRIDGE_ROOT/out/uafx_kvm_mock_seed.json"
BRIDGE_DEMO_SCRIPT="$BRIDGE_ROOT/scripts/run_end_to_end_kvm_demo.sh"
IMPORT_TOOL="$MOCK_ROOT/tools/import_bridge_seed.py"
PYTHON_BIN="${PYTHON:-python3}"

require_dir "$BRIDGE_ROOT" "bridge root not found: $BRIDGE_ROOT"
require_file "$BRIDGE_DEMO_SCRIPT" "bridge demo script not found: $BRIDGE_DEMO_SCRIPT"
require_file "$IMPORT_TOOL" "bridge seed importer not found: $IMPORT_TOOL"
require_cmd "$PYTHON_BIN"

cd "$BRIDGE_ROOT"
bash "$BRIDGE_DEMO_SCRIPT"
require_file "$SEED_JSON" "bridge demo did not produce seed artifact: $SEED_JSON"

cd "$MOCK_ROOT"
"$PYTHON_BIN" "$IMPORT_TOOL" "$SEED_JSON" --output-dir "$SEED_OUT_DIR" --dry-run
require_dir "$SEED_OUT_DIR/input" "seed input directory not created: $SEED_OUT_DIR/input"
require_file "$SEED_OUT_DIR/relations/bridge_seed.relations" "seed relations file not created: $SEED_OUT_DIR/relations/bridge_seed.relations"
require_file "$SEED_OUT_DIR/bias.json" "seed bias file not created: $SEED_OUT_DIR/bias.json"

echo
echo "Prepared seeded fuzzing workdir: $SEED_OUT_DIR"
echo "  input programs : $SEED_OUT_DIR/input"
echo "  relations file : $SEED_OUT_DIR/relations/bridge_seed.relations"
echo "  bias summary   : $SEED_OUT_DIR/bias.json"
