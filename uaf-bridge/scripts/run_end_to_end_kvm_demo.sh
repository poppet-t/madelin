#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -x "$ROOT/.venv_ci/bin/python" ]]; then
  PYTHON="$ROOT/.venv_ci/bin/python"
elif [[ -x "$ROOT/.venv_sys/bin/python" ]]; then
  PYTHON="$ROOT/.venv_sys/bin/python"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="python3"
fi

INPUT="uafx_fork/samples/raw_uafx_kvm_warning.json"
EXPORT="out/uafx_kvm_bridge_export.json"
CANDIDATE="out/uafx_kvm_candidate.json"
PLAN="out/uafx_kvm_plan.json"
WITNESS="out/uafx_kvm_witness.syz"
SEED="out/uafx_kvm_mock_seed.json"
ADAPTER="out/uafx_kvm_mock_adapter.json"
PROGRAM="out/uafx_kvm_mock_program.txt"
PROOF_DIR="out/uafx_kvm_proof"

printf 'Using Python: %s\n' "$PYTHON"

"$PYTHON" -m uafx_fork.tools.export_bridge_candidate \
  --input "$INPUT" \
  --output "$EXPORT"

"$PYTHON" -m extractor.import_uafx_bridge_export \
  --input "$EXPORT" \
  --output "$CANDIDATE"

"$PYTHON" -m smt.solve_candidate \
  --input "$CANDIDATE" \
  --output "$PLAN"

"$PYTHON" -m runtime.emit_witness_syz \
  --candidate "$CANDIDATE" \
  --plan "$PLAN" \
  --output "$WITNESS"

"$PYTHON" -m runtime.export_mock_seed \
  --candidate "$CANDIDATE" \
  --plan "$PLAN" \
  --output "$SEED"

"$PYTHON" -m mock_adapter.import_seed \
  --input "$SEED" \
  --output "$ADAPTER"

"$PYTHON" -m mock_adapter.seed_to_mock_program \
  --input "$SEED" \
  --output "$PROGRAM"

"$PYTHON" -m proof.package_artifacts \
  --candidate "$CANDIDATE" \
  --plan "$PLAN" \
  --witness "$WITNESS" \
  --output-dir "$PROOF_DIR"

printf '\nArtifacts created:\n'
printf '  %s\n' "$EXPORT" "$CANDIDATE" "$PLAN" "$WITNESS" "$SEED" "$ADAPTER" "$PROGRAM" "$PROOF_DIR/summary.json" "$PROOF_DIR/proof.md"
