#!/usr/bin/env bash
set -euo pipefail

MOCK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec bash "$MOCK_ROOT/scripts/run_kvm_seed_fuzz.sh" "$@"
