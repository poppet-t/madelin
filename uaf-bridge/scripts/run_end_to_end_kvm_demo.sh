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
printf '[1/8] Exporting bridge candidate...\n'

"$PYTHON" -m uafx_fork.tools.export_bridge_candidate \
  --input "$INPUT" \
  --output "$EXPORT"

printf '[2/8] Importing canonical candidate...\n'
"$PYTHON" -m extractor.import_uafx_bridge_export \
  --input "$EXPORT" \
  --output "$CANDIDATE"

printf '[3/8] Solving witness plan...\n'
"$PYTHON" -m smt.solve_candidate \
  --input "$CANDIDATE" \
  --output "$PLAN"

printf '[4/8] Emitting witness scaffold...\n'
"$PYTHON" -m runtime.emit_witness_syz \
  --candidate "$CANDIDATE" \
  --plan "$PLAN" \
  --output "$WITNESS"

printf '[5/8] Exporting MOCK seed...\n'
"$PYTHON" -m runtime.export_mock_seed \
  --candidate "$CANDIDATE" \
  --plan "$PLAN" \
  --output "$SEED"

printf '[6/8] Importing MOCK adapter JSON...\n'
"$PYTHON" -m mock_adapter.import_seed \
  --input "$SEED" \
  --output "$ADAPTER"

printf '[7/8] Rendering MOCK textual scaffold...\n'
"$PYTHON" -m mock_adapter.seed_to_mock_program \
  --input "$SEED" \
  --output "$PROGRAM"

printf '[8/8] Packaging proof artifacts...\n'
"$PYTHON" -m proof.package_artifacts \
  --candidate "$CANDIDATE" \
  --plan "$PLAN" \
  --witness "$WITNESS" \
  --output-dir "$PROOF_DIR"

if [[ ! -f "$SEED" ]]; then
  printf 'error: expected seed artifact not found: %s\n' "$SEED" >&2
  exit 1
fi

printf '\nArtifacts created:\n'
printf '  %s\n' "$EXPORT" "$CANDIDATE" "$PLAN" "$WITNESS" "$SEED" "$ADAPTER" "$PROGRAM" "$PROOF_DIR/summary.json" "$PROOF_DIR/proof.md"
