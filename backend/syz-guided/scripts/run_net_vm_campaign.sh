#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(cd "$BACKEND_DIR/../.." && pwd)"
BRIDGE_ROOT="$REPO_ROOT/uaf-bridge"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
PROGRESS_PID=""

if [[ -f "$BRIDGE_ROOT/scripts/_bridge_python.sh" ]]; then
  # shellcheck disable=SC1091
  source "$BRIDGE_ROOT/scripts/_bridge_python.sh"
else
  echo "Missing bridge python selector at $BRIDGE_ROOT/scripts/_bridge_python.sh" >&2
  exit 1
fi

usage() {
  cat >&2 <<'USAGE'
Usage: run_net_vm_campaign.sh \
  --kernel <path> \
  --ssh-key <path> \
  [--proof-mode <off|controlled|organic>] \
  [--proof-kernel-meta <path>] \
  [--syz-execprog <path>] \
  [--syz-executor <path>] \
  [--disk-image <path>] \
  [--guest-syz-executor-path <path>] \
  [--guest-syz-execprog-path <path>] \
  [--guest-extra-append <kernel-cmdline>] \
  [--single-seed-only] \
  [--bridge-export <path>] \
  [--out-dir <path>] \
  [--timeout-sec <seconds>] \
  [--procs <n>] \
  [--ssh-port <port>] \
  [--boot-timeout <seconds>] \
  [--repro-attempts <n>] \
  [--extended-rounds <n>] \
  [--threaded] \
  [--known-bug-review <path>]

This is the live arm64 nf_tables validation entrypoint. It always performs:
  bridge -> witness -> state model -> seeds -> strict live preflight ->
  single-seed validation -> four-seed validation -> short bounded campaign ->
  repro / duplicate hygiene / final verdict.

Strict live preflight is mandatory. The run fails before campaign execution if:
  - syz-execprog is neither staged from the host nor already present in the guest
  - syz-executor is neither staged from the host nor already present in the guest
  - kernel / disk / ssh setup is invalid
  - QEMU boot or non-interactive SSH fails
  - guest networking is absent
  - debugfs is missing or cannot be mounted
  - required kernel config or nf_tables support is missing
  - syz-execprog does not expose KCOV coverfile support
USAGE
  exit 2
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

stop_progress_renderer() {
  if [[ -n "$PROGRESS_PID" ]]; then
    kill "$PROGRESS_PID" >/dev/null 2>&1 || true
    wait "$PROGRESS_PID" 2>/dev/null || true
    PROGRESS_PID=""
  fi
}

render_progress() {
  local progress_file="$1"
  while true; do
    if [[ -f "$progress_file" ]]; then
      python3 - <<'PY' "$progress_file"
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
try:
    data = json.loads(path.read_text())
except Exception:
    raise SystemExit(0)

stage_index = data.get("stage_index", "?")
stage_total = data.get("stage_total", "?")
stage_name = data.get("stage_name", "unknown")
substage = data.get("substage", "unknown")
status = data.get("status", "unknown")
seed = data.get("seed")
current = data.get("current")
total = data.get("total")
elapsed = data.get("elapsed_sec")
timeout = data.get("timeout_sec")
detail = data.get("detail")

def bar(cur, tot, width=20):
    if not isinstance(cur, int) or not isinstance(tot, int) or tot <= 0:
        return None
    done = max(0, min(width, int((cur / tot) * width)))
    return "[" + ("#" * done) + ("-" * (width - done)) + f"] {cur}/{tot}"

parts = [f"[progress] {stage_index}/{stage_total} {stage_name}", f"{substage}", f"status={status}"]
b = bar(current, total)
if b:
    parts.append(b)
if seed:
    parts.append(f"seed={seed}")
if isinstance(elapsed, (int, float)) and isinstance(timeout, int):
    parts.append(f"elapsed={int(elapsed)}s/{timeout}s")
elif isinstance(elapsed, (int, float)):
    parts.append(f"elapsed={int(elapsed)}s")
if detail:
    parts.append(f"detail={detail}")
print(" | ".join(parts))
PY
    fi
    sleep 2
  done
}

SYZ_EXECPROG=""
SYZ_EXECUTOR=""
GUEST_SYZ_EXECPROG_PATH="/usr/local/bin/syz-execprog"
GUEST_SYZ_EXECUTOR_PATH="/usr/local/bin/syz-executor"
GUEST_EXTRA_APPEND="systemd.unit=multi-user.target fsck.mode=skip systemd.default_timeout_start_sec=15s systemd.mask=serial-getty@ttyAMA0.service systemd.mask=systemd-networkd-wait-online.service systemd.mask=multipathd.service systemd.mask=boot.mount systemd.mask=boot-efi.mount"
DEFAULT_LIVE_IMAGE="$REPO_ROOT/syzkaller-runtime-export/arm64-live-ready.qcow2"
DEFAULT_HOST_SYZ_EXECPROG="$REPO_ROOT/syzkaller/bin/linux_arm64/syz-execprog"
DEFAULT_HOST_SYZ_EXECUTOR="$REPO_ROOT/syzkaller/bin/linux_arm64/syz-executor"
KERNEL_IMAGE=""
DISK_IMAGE=""
SSH_KEY=""
BRIDGE_EXPORT="$BRIDGE_ROOT/extractor/sample_uafx_net_bridge_export.json"
OUT_DIR="$REPO_ROOT/out/net-runtime/live-$TIMESTAMP"
TIMEOUT_SEC=180
PROCS=1
THREADED=0
SSH_PORT=10022
BOOT_TIMEOUT=300
REPRO_ATTEMPTS=3
EXTENDED_ROUNDS=0
KNOWN_BUG_REVIEW=""
STOP_AFTER_STAGE=""
PROOF_MODE="controlled"
PROOF_KERNEL_META=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --syz-execprog) SYZ_EXECPROG="${2:-}"; shift 2 ;;
    --syz-executor) SYZ_EXECUTOR="${2:-}"; shift 2 ;;
    --guest-syz-execprog-path) GUEST_SYZ_EXECPROG_PATH="${2:-}"; shift 2 ;;
    --guest-syz-executor-path) GUEST_SYZ_EXECUTOR_PATH="${2:-}"; shift 2 ;;
    --guest-extra-append) GUEST_EXTRA_APPEND="${2:-}"; shift 2 ;;
    --kernel) KERNEL_IMAGE="${2:-}"; shift 2 ;;
    --disk-image) DISK_IMAGE="${2:-}"; shift 2 ;;
    --ssh-key) SSH_KEY="${2:-}"; shift 2 ;;
    --bridge-export) BRIDGE_EXPORT="${2:-}"; shift 2 ;;
    --out-dir) OUT_DIR="${2:-}"; shift 2 ;;
    --timeout-sec) TIMEOUT_SEC="${2:-}"; shift 2 ;;
    --procs) PROCS="${2:-}"; shift 2 ;;
    --ssh-port) SSH_PORT="${2:-}"; shift 2 ;;
    --boot-timeout) BOOT_TIMEOUT="${2:-}"; shift 2 ;;
    --repro-attempts) REPRO_ATTEMPTS="${2:-}"; shift 2 ;;
    --extended-rounds) EXTENDED_ROUNDS="${2:-}"; shift 2 ;;
    --known-bug-review) KNOWN_BUG_REVIEW="${2:-}"; shift 2 ;;
    --single-seed-only) STOP_AFTER_STAGE="single-seed-validation"; shift ;;
    --proof-mode) PROOF_MODE="${2:-}"; shift 2 ;;
    --proof-kernel-meta) PROOF_KERNEL_META="${2:-}"; shift 2 ;;
    --threaded) THREADED=1; shift ;;
    -h|--help) usage ;;
    *) echo "Unknown argument: $1" >&2; usage ;;
  esac
done

if [[ -z "$DISK_IMAGE" && -f "$DEFAULT_LIVE_IMAGE" ]]; then
  DISK_IMAGE="$DEFAULT_LIVE_IMAGE"
fi

[[ -n "$KERNEL_IMAGE" && -n "$DISK_IMAGE" && -n "$SSH_KEY" ]] || usage
[[ -f "$BRIDGE_EXPORT" ]] || { echo "Missing bridge export: $BRIDGE_EXPORT" >&2; exit 1; }

require_cmd python3
BRIDGE_PYTHON="$(select_bridge_python "$BRIDGE_ROOT")"

mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"
ln -sfn "$OUT_DIR" "$REPO_ROOT/out/net-runtime/latest"

BRIDGE_OUT="$OUT_DIR/bridge"
ARTIFACTS_OUT="$OUT_DIR/artifacts"
SEEDS_OUT="$OUT_DIR/seeds"
CAMPAIGN_OUT="$OUT_DIR/campaign"
RUNTIME_OUT="$OUT_DIR/runtime"
PRELIGHT_OUT="$OUT_DIR/preflight"
CRASH_OUT="$OUT_DIR/crashes"
REPRO_OUT="$OUT_DIR/repro"
LOGS_OUT="$OUT_DIR/logs"
mkdir -p "$BRIDGE_OUT" "$ARTIFACTS_OUT" "$SEEDS_OUT" "$CAMPAIGN_OUT" "$RUNTIME_OUT" "$PRELIGHT_OUT" "$CRASH_OUT" "$REPRO_OUT" "$LOGS_OUT"

CANDIDATE_PATH="$BRIDGE_OUT/candidate.json"
PLAN_PATH="$BRIDGE_OUT/witness_plan.json"
WITNESS_PATH="$BRIDGE_OUT/witness.syz"
HARNESS_PATH="$BRIDGE_OUT/harness.c"

printf '[net-live] output root: %s\n' "$OUT_DIR"
printf '[net-live] 1/7 import bridge export -> candidate\n'
(
  cd "$BRIDGE_ROOT"
  "$BRIDGE_PYTHON" -m extractor.import_uafx_bridge_export --input "$BRIDGE_EXPORT" --output "$CANDIDATE_PATH"
)

printf '[net-live] 2/7 solve candidate -> witness plan\n'
(
  cd "$BRIDGE_ROOT"
  "$BRIDGE_PYTHON" -m smt.solve_candidate --input "$CANDIDATE_PATH" --output "$PLAN_PATH"
)

printf '[net-live] 3/7 emit witness + harness\n'
(
  cd "$BRIDGE_ROOT"
  "$BRIDGE_PYTHON" -m runtime.emit_witness_syz --candidate "$CANDIDATE_PATH" --plan "$PLAN_PATH" --output "$WITNESS_PATH"
  "$BRIDGE_PYTHON" -m harness.generate_harness --candidate "$CANDIDATE_PATH" --plan "$PLAN_PATH" --output "$HARNESS_PATH"
)

printf '[net-live] 4/7 build backend artifacts\n'
python3 "$BACKEND_DIR/state_model/build_state_model.py" \
  --candidate "$CANDIDATE_PATH" \
  --witness-plan "$PLAN_PATH" \
  --out-dir "$ARTIFACTS_OUT"

printf '[net-live] 5/7 synthesize seeds\n'
python3 "$BACKEND_DIR/seedgen/synthesize_seeds.py" \
  --state-model "$ARTIFACTS_OUT/state_model_v1.json" \
  --out-dir "$SEEDS_OUT"

printf '[net-live] 6/7 bounded artifact-level campaign\n'
python3 "$BACKEND_DIR/orchestrator/campaign.py" \
  --artifacts-dir "$ARTIFACTS_OUT" \
  --seeds-dir "$SEEDS_OUT" \
  --work-dir "$CAMPAIGN_OUT" \
  --max-iterations 20

RUNTIME_ARGS=(
  --state-model "$ARTIFACTS_OUT/state_model_v1.json"
  --target-profile "$ARTIFACTS_OUT/target_profile.json"
  --seeds-dir "$SEEDS_OUT"
  --kernel "$KERNEL_IMAGE"
  --disk-image "$DISK_IMAGE"
  --ssh-key "$SSH_KEY"
  --ssh-port "$SSH_PORT"
  --out-dir "$OUT_DIR"
  --timeout-sec "$TIMEOUT_SEC"
  --procs "$PROCS"
  --boot-timeout "$BOOT_TIMEOUT"
  --repro-attempts "$REPRO_ATTEMPTS"
  --extended-rounds "$EXTENDED_ROUNDS"
  --guest-syz-execprog-path "$GUEST_SYZ_EXECPROG_PATH"
  --guest-syz-executor-path "$GUEST_SYZ_EXECUTOR_PATH"
  --proof-mode "$PROOF_MODE"
)
if [[ -n "$GUEST_EXTRA_APPEND" ]]; then
  RUNTIME_ARGS+=(--guest-extra-append "$GUEST_EXTRA_APPEND")
fi
if [[ -n "$SYZ_EXECPROG" ]]; then
  RUNTIME_ARGS+=(--syz-execprog "$SYZ_EXECPROG")
fi
if [[ -n "$SYZ_EXECUTOR" ]]; then
  RUNTIME_ARGS+=(--syz-executor "$SYZ_EXECUTOR")
fi
if [[ "$THREADED" -eq 1 ]]; then
  RUNTIME_ARGS+=(--threaded)
fi
if [[ -n "$KNOWN_BUG_REVIEW" ]]; then
  RUNTIME_ARGS+=(--known-bug-review "$KNOWN_BUG_REVIEW")
fi
if [[ -n "$STOP_AFTER_STAGE" ]]; then
  RUNTIME_ARGS+=(--stop-after-stage "$STOP_AFTER_STAGE")
fi
if [[ -n "$PROOF_KERNEL_META" ]]; then
  RUNTIME_ARGS+=(--proof-kernel-meta "$PROOF_KERNEL_META")
fi

printf '[net-live] 7/7 strict live runtime lane\n'
render_progress "$LOGS_OUT/progress.json" &
PROGRESS_PID=$!
trap stop_progress_renderer EXIT
python3 "$BACKEND_DIR/runtime/net_lane.py" "${RUNTIME_ARGS[@]}"
stop_progress_renderer
trap - EXIT

python3 - <<'PY' "$OUT_DIR"
import json
import pathlib
import sys
base = pathlib.Path(sys.argv[1])
preflight = json.loads((base / 'preflight' / 'preflight_summary.json').read_text())
verdict = json.loads((base / 'runtime' / 'final_verdict.json').read_text())
execution = json.loads((base / 'runtime' / 'execution_evidence_summary.json').read_text()) if (base / 'runtime' / 'execution_evidence_summary.json').exists() else {}
crash = json.loads((base / 'runtime' / 'crash_evidence_summary.json').read_text()) if (base / 'runtime' / 'crash_evidence_summary.json').exists() else {}
repro = json.loads((base / 'repro' / crash.get('primary_seed', 'missing') / 'repro_summary.json').read_text()) if crash.get('primary_seed') and (base / 'repro' / crash.get('primary_seed', 'missing') / 'repro_summary.json').exists() else {'classification': 'not-attempted'}
print('Preflight ready:', preflight['ready'])
print('Runtime verdict:', verdict['verdict_class'])
print('Phase reached:', execution.get('phase_reached'))
print('Target reached:', execution.get('target_family_hit'))
print('Crash kind:', crash.get('crash_kind'))
print('Crash signature:', crash.get('signature'))
print('Repro status:', repro.get('classification'))
print('Artifacts:', base)
PY
