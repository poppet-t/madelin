#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
BRIDGE_ROOT="${VERIFY_BRIDGE_ROOT:-$REPO_ROOT/uaf-bridge}"
MOCK_ROOT="${VERIFY_MOCK_ROOT:-$REPO_ROOT/mock}"

RUN_WITNESS_SCRIPT="${VERIFY_RUN_WITNESS_SCRIPT:-$MOCK_ROOT/scripts/run_witness.sh}"
RUN_HARNESS_SCRIPT="${VERIFY_RUN_HARNESS_SCRIPT:-$MOCK_ROOT/scripts/run_harness.sh}"
RUN_FUZZ_SCRIPT="${VERIFY_RUN_FUZZ_SCRIPT:-$MOCK_ROOT/scripts/run_kvm_seed_fuzz.sh}"
IMPORT_SEED_TOOL="${VERIFY_IMPORT_SEED_TOOL:-$MOCK_ROOT/tools/import_bridge_seed.py}"

usage() {
  cat >&2 <<'EOF'
usage: verify_candidate.sh --candidate <path> [--strategy harness|witness|fuzz|all] [--artifacts-root <path>] [--timeout <seconds>] [--dry-run]
                           [--target-host <host>|<user@host>] [--ssh-key <path>] [--ssh-user <user>] [--ssh-port <port>]
                           [--disk-image <path>] [--kernel-image <path>] [--syz-dir <path>]
                           [--witness-runs <n>] [--timing-range <csv>] [--runs-per-timing <n>] [--fuzz-max-seconds <n>]

strategy requirements:
  harness: --target-host --ssh-key
  witness: --target-host --ssh-key
  fuzz:    --disk-image --ssh-key --kernel-image
  all:     union of harness/witness/fuzz requirements
EOF
  exit 1
}

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

run_with_timeout() {
  local timeout_seconds="$1"
  shift

  if [[ -z "$timeout_seconds" ]]; then
    "$@"
    return 0
  fi

  "$PYTHON_BIN" - "$timeout_seconds" "$@" <<'PY'
import subprocess
import sys

timeout_seconds = int(sys.argv[1])
cmd = sys.argv[2:]
try:
    completed = subprocess.run(cmd, check=False, timeout=timeout_seconds)
except subprocess.TimeoutExpired:
    print(
        f"error: command timed out after {timeout_seconds}s: {' '.join(cmd)}",
        file=sys.stderr,
    )
    sys.exit(124)
sys.exit(completed.returncode)
PY
}

run_logged_step() {
  local stdout_log="$1"
  local stderr_log="$2"
  local timeout_seconds="$3"
  shift 3

  set +e
  if [[ -n "$timeout_seconds" ]]; then
    run_with_timeout "$timeout_seconds" "$@" >"$stdout_log" 2>"$stderr_log"
  else
    "$@" >"$stdout_log" 2>"$stderr_log"
  fi
  local rc=$?
  set -e
  return "$rc"
}

current_utc_timestamp() {
  "$PYTHON_BIN" - <<'PY'
from datetime import datetime, timezone
print(datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"))
PY
}

remaining_timeout() {
  if [[ -z "$TIMEOUT_SECONDS" ]]; then
    printf '\n'
    return 0
  fi

  local now
  now="$(date +%s)"
  local remaining=$((TIMEOUT_DEADLINE - now))
  if [[ "$remaining" -le 0 ]]; then
    printf '0\n'
    return 0
  fi
  printf '%s\n' "$remaining"
}

normalize_target_host() {
  if [[ "$TARGET_HOST" == *"@"* && "$SSH_USER_EXPLICIT" -eq 0 ]]; then
    SSH_USER="${TARGET_HOST%@*}"
    TARGET_HOST="${TARGET_HOST#*@}"
  fi
}

copy_candidate_into_artifact_dir() {
  if [[ "$CANDIDATE_SOURCE" != "$CANDIDATE_ARTIFACT" ]]; then
    cp "$CANDIDATE_SOURCE" "$CANDIDATE_ARTIFACT"
  fi
}

run_solve_candidate() {
  if [[ -n "${VERIFY_SOLVE_CANDIDATE_CMD:-}" ]]; then
    "$VERIFY_SOLVE_CANDIDATE_CMD" "$@"
  else
    (
      cd "$BRIDGE_ROOT"
      "$PYTHON_BIN" -m smt.solve_candidate "$@"
    )
  fi
}

run_emit_witness() {
  if [[ -n "${VERIFY_EMIT_WITNESS_CMD:-}" ]]; then
    "$VERIFY_EMIT_WITNESS_CMD" "$@"
  else
    (
      cd "$BRIDGE_ROOT"
      "$PYTHON_BIN" -m runtime.emit_witness_syz "$@"
    )
  fi
}

run_generate_harness() {
  if [[ -n "${VERIFY_GENERATE_HARNESS_CMD:-}" ]]; then
    "$VERIFY_GENERATE_HARNESS_CMD" "$@"
  else
    (
      cd "$BRIDGE_ROOT"
      "$PYTHON_BIN" -m harness.generate_harness "$@"
    )
  fi
}

run_export_mock_seed() {
  if [[ -n "${VERIFY_EXPORT_MOCK_SEED_CMD:-}" ]]; then
    "$VERIFY_EXPORT_MOCK_SEED_CMD" "$@"
  else
    (
      cd "$BRIDGE_ROOT"
      "$PYTHON_BIN" -m runtime.export_mock_seed "$@"
    )
  fi
}

run_import_seed() {
  if [[ -n "${VERIFY_IMPORT_SEED_CMD:-}" ]]; then
    "$VERIFY_IMPORT_SEED_CMD" "$@"
  else
    "$PYTHON_BIN" "$IMPORT_SEED_TOOL" "$@"
  fi
}

emit_synthetic_verdict() {
  local verdict_kind="$1"
  local execution_mode="$2"

  PYTHONPATH="$MOCK_ROOT" "$PYTHON_BIN" - "$CANDIDATE_ARTIFACT" "$CANDIDATE_DIR" "$verdict_kind" "$execution_mode" <<'PY'
from pathlib import Path
import sys

from verdict.emit_verdict import emit_verdict

candidate_path = Path(sys.argv[1])
output_dir = Path(sys.argv[2])
verdict_kind = sys.argv[3]
execution_mode = sys.argv[4]

metadata = {"execution_mode": execution_mode}
if verdict_kind == "SETUP_FAILED":
    metadata["setup_failed"] = True
elif verdict_kind == "PATH_INFEASIBLE":
    metadata["path_infeasible"] = True
elif verdict_kind == "REACHED_NO_CRASH":
    metadata["execution_completed"] = True

emit_verdict(output_dir=output_dir, candidate_path=candidate_path, execution_metadata=metadata)
PY
}

write_strategy_record() {
  local strategy_name="$1"
  local output_dir="$2"
  local exit_code="$3"
  local timed_out="$4"
  local started_at="$5"
  local finished_at="$6"
  local stdout_log="$7"
  local stderr_log="$8"
  local attempt_index="$9"

  "$PYTHON_BIN" - "$output_dir/orchestrator.json" "$strategy_name" "$output_dir" "$exit_code" "$timed_out" \
    "$started_at" "$finished_at" "$stdout_log" "$stderr_log" "$attempt_index" <<'PY'
from pathlib import Path
import json
import sys

path = Path(sys.argv[1])
payload = {
    "attempt_index": int(sys.argv[10]),
    "command_exit_code": int(sys.argv[4]),
    "finished_at": sys.argv[7],
    "output_dir": sys.argv[3],
    "started_at": sys.argv[6],
    "stderr_log": sys.argv[9],
    "stdout_log": sys.argv[8],
    "strategy": sys.argv[2],
    "timed_out": sys.argv[5] == "1",
    "verdict_path": str(Path(sys.argv[3]) / "verdict.json"),
}
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

strategy_verdict() {
  local verdict_path="$1"
  if [[ ! -f "$verdict_path" ]]; then
    printf '\n'
    return 0
  fi

  "$PYTHON_BIN" - "$verdict_path" <<'PY'
from pathlib import Path
import json
import sys

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload.get("verdict", ""))
PY
}

ensure_timeout_remaining() {
  local remaining
  remaining="$(remaining_timeout)"
  if [[ "$remaining" == "0" ]]; then
    note "candidate timeout expired before the next step started"
    if [[ "$DRY_RUN" -eq 0 ]]; then
      emit_synthetic_verdict "SETUP_FAILED" "verify_candidate_timeout"
    fi
    return 1
  fi
  return 0
}

ensure_witness_plan() {
  if [[ -f "$WITNESS_PLAN_PATH" ]]; then
    return 0
  fi

  ensure_timeout_remaining || return 1

  local stdout_log="$LOG_DIR/solve_candidate.stdout.log"
  local stderr_log="$LOG_DIR/solve_candidate.stderr.log"
  local timeout_seconds
  timeout_seconds="$(remaining_timeout)"
  if ! run_logged_step "$stdout_log" "$stderr_log" "$timeout_seconds" \
    run_solve_candidate --input "$CANDIDATE_ARTIFACT" --output "$WITNESS_PLAN_PATH"; then
    if [[ "$DRY_RUN" -eq 0 ]]; then
      emit_synthetic_verdict "SETUP_FAILED" "verify_candidate_prepare"
    fi
    return 1
  fi

  local plan_sat
  plan_sat="$("$PYTHON_BIN" - "$WITNESS_PLAN_PATH" <<'PY'
from pathlib import Path
import json
import sys

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print("1" if payload.get("sat", False) else "0")
PY
)"
  if [[ "$plan_sat" != "1" ]]; then
    if [[ "$DRY_RUN" -eq 0 ]]; then
      emit_synthetic_verdict "PATH_INFEASIBLE" "verify_candidate_plan_unsat"
    fi
    return 2
  fi
  return 0
}

ensure_witness_source() {
  if [[ -f "$WITNESS_SOURCE_PATH" ]]; then
    return 0
  fi

  ensure_witness_plan
  local plan_rc=$?
  if [[ "$plan_rc" -ne 0 ]]; then
    return "$plan_rc"
  fi

  ensure_timeout_remaining || return 1

  local stdout_log="$LOG_DIR/emit_witness.stdout.log"
  local stderr_log="$LOG_DIR/emit_witness.stderr.log"
  local timeout_seconds
  timeout_seconds="$(remaining_timeout)"
  local cmd=(--candidate "$CANDIDATE_ARTIFACT" --plan "$WITNESS_PLAN_PATH" --output "$WITNESS_SOURCE_PATH")
  if [[ -n "$SYZ_DIR" ]]; then
    cmd+=(--syz-root "$SYZ_DIR")
  fi
  if ! run_logged_step "$stdout_log" "$stderr_log" "$timeout_seconds" run_emit_witness "${cmd[@]}"; then
    if [[ "$DRY_RUN" -eq 0 ]]; then
      emit_synthetic_verdict "SETUP_FAILED" "verify_candidate_prepare"
    fi
    return 1
  fi
  return 0
}

ensure_harness_source() {
  if [[ -f "$HARNESS_SOURCE_PATH" ]]; then
    return 0
  fi

  ensure_witness_plan
  local plan_rc=$?
  if [[ "$plan_rc" -ne 0 ]]; then
    return "$plan_rc"
  fi

  ensure_timeout_remaining || return 1

  local stdout_log="$LOG_DIR/generate_harness.stdout.log"
  local stderr_log="$LOG_DIR/generate_harness.stderr.log"
  local timeout_seconds
  timeout_seconds="$(remaining_timeout)"
  if ! run_logged_step "$stdout_log" "$stderr_log" "$timeout_seconds" \
    run_generate_harness --candidate "$CANDIDATE_ARTIFACT" --plan "$WITNESS_PLAN_PATH" --output "$HARNESS_SOURCE_PATH"; then
    if [[ "$DRY_RUN" -eq 0 ]]; then
      emit_synthetic_verdict "SETUP_FAILED" "verify_candidate_prepare"
    fi
    return 1
  fi
  return 0
}

ensure_mock_seed() {
  if [[ -f "$MOCK_SEED_PATH" && -d "$SEED_WORKDIR" ]]; then
    return 0
  fi

  ensure_witness_plan
  local plan_rc=$?
  if [[ "$plan_rc" -ne 0 ]]; then
    return "$plan_rc"
  fi

  ensure_timeout_remaining || return 1

  local export_stdout="$LOG_DIR/export_mock_seed.stdout.log"
  local export_stderr="$LOG_DIR/export_mock_seed.stderr.log"
  local timeout_seconds
  timeout_seconds="$(remaining_timeout)"
  if ! run_logged_step "$export_stdout" "$export_stderr" "$timeout_seconds" \
    run_export_mock_seed --candidate "$CANDIDATE_ARTIFACT" --plan "$WITNESS_PLAN_PATH" --output "$MOCK_SEED_PATH"; then
    if [[ "$DRY_RUN" -eq 0 ]]; then
      emit_synthetic_verdict "SETUP_FAILED" "verify_candidate_prepare"
    fi
    return 1
  fi

  local import_stdout="$LOG_DIR/import_seed.stdout.log"
  local import_stderr="$LOG_DIR/import_seed.stderr.log"
  timeout_seconds="$(remaining_timeout)"
  if ! run_logged_step "$import_stdout" "$import_stderr" "$timeout_seconds" \
    run_import_seed "$MOCK_SEED_PATH" --output-dir "$SEED_WORKDIR"; then
    if [[ "$DRY_RUN" -eq 0 ]]; then
      emit_synthetic_verdict "SETUP_FAILED" "verify_candidate_prepare"
    fi
    return 1
  fi
  return 0
}

run_strategy_command() {
  local strategy_name="$1"
  shift

  local output_dir="$STRATEGIES_DIR/$strategy_name"
  mkdir -p "$output_dir"
  local stdout_log="$LOG_DIR/${strategy_name}.stdout.log"
  local stderr_log="$LOG_DIR/${strategy_name}.stderr.log"
  local started_at
  local finished_at
  local timeout_seconds
  started_at="$(current_utc_timestamp)"
  timeout_seconds="$(remaining_timeout)"

  set +e
  run_logged_step "$stdout_log" "$stderr_log" "$timeout_seconds" "$@"
  local rc=$?
  set -e

  finished_at="$(current_utc_timestamp)"
  ATTEMPT_COUNTER=$((ATTEMPT_COUNTER + 1))
  local timed_out=0
  if [[ "$rc" -eq 124 ]]; then
    timed_out=1
    if [[ "$DRY_RUN" -eq 0 && ! -f "$output_dir/verdict.json" ]]; then
      emit_synthetic_verdict "SETUP_FAILED" "verify_candidate_timeout"
    fi
  fi

  write_strategy_record \
    "$strategy_name" \
    "$output_dir" \
    "$rc" \
    "$timed_out" \
    "$started_at" \
    "$finished_at" \
    "$stdout_log" \
    "$stderr_log" \
    "$ATTEMPT_COUNTER"

  local verdict_text
  verdict_text="$(strategy_verdict "$output_dir/verdict.json")"
  if [[ -n "$verdict_text" ]]; then
    printf 'Strategy %s verdict: %s\n' "$strategy_name" "$verdict_text"
  else
    printf 'Strategy %s exit code: %s\n' "$strategy_name" "$rc"
  fi
  return 0
}

run_harness_strategy() {
  local prep_rc=0
  set +e
  ensure_harness_source
  prep_rc=$?
  set -e
  if [[ "$prep_rc" -ne 0 ]]; then
    return "$prep_rc"
  fi

  local cmd=()
  if [[ "$RUN_HARNESS_SCRIPT" == *.sh ]]; then
    cmd=(bash "$RUN_HARNESS_SCRIPT")
  else
    cmd=("$RUN_HARNESS_SCRIPT")
  fi
  cmd+=(
    --harness "$HARNESS_SOURCE_PATH"
    --candidate "$CANDIDATE_ARTIFACT"
    --target-host "$TARGET_HOST"
    --ssh-key "$SSH_KEY"
    --ssh-user "$SSH_USER"
    --ssh-port "$SSH_PORT"
    --timing-range "$TIMING_RANGE"
    --runs-per-timing "$RUNS_PER_TIMING"
    --output-dir "$STRATEGIES_DIR/harness"
  )
  if [[ "$DRY_RUN" -eq 1 ]]; then
    cmd+=(--dry-run)
  fi

  run_strategy_command harness "${cmd[@]}"
}

run_witness_strategy() {
  local prep_rc=0
  set +e
  ensure_witness_source
  prep_rc=$?
  set -e
  if [[ "$prep_rc" -ne 0 ]]; then
    return "$prep_rc"
  fi

  local cmd=()
  if [[ "$RUN_WITNESS_SCRIPT" == *.sh ]]; then
    cmd=(bash "$RUN_WITNESS_SCRIPT")
  else
    cmd=("$RUN_WITNESS_SCRIPT")
  fi
  cmd+=(
    --witness "$WITNESS_SOURCE_PATH"
    --candidate "$CANDIDATE_ARTIFACT"
    --target-host "$TARGET_HOST"
    --ssh-key "$SSH_KEY"
    --ssh-user "$SSH_USER"
    --ssh-port "$SSH_PORT"
    --runs "$WITNESS_RUNS"
    --output-dir "$STRATEGIES_DIR/witness"
  )
  if [[ -n "$SYZ_DIR" ]]; then
    cmd+=(--syz-dir "$SYZ_DIR")
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    cmd+=(--dry-run)
  fi

  run_strategy_command witness "${cmd[@]}"
}

run_fuzz_strategy() {
  local prep_rc=0
  set +e
  ensure_mock_seed
  prep_rc=$?
  set -e
  if [[ "$prep_rc" -ne 0 ]]; then
    return "$prep_rc"
  fi

  local cmd=()
  if [[ "$RUN_FUZZ_SCRIPT" == *.sh ]]; then
    cmd=(bash "$RUN_FUZZ_SCRIPT")
  else
    cmd=("$RUN_FUZZ_SCRIPT")
  fi

  local fuzz_seconds="$FUZZ_MAX_SECONDS"
  if [[ -z "$fuzz_seconds" ]]; then
    fuzz_seconds="$(remaining_timeout)"
  elif [[ -n "$TIMEOUT_SECONDS" ]]; then
    local remaining
    remaining="$(remaining_timeout)"
    if [[ -n "$remaining" && "$remaining" != "0" && "$remaining" -lt "$fuzz_seconds" ]]; then
      fuzz_seconds="$remaining"
    fi
  fi

  cmd+=(
    --seed-workdir "$SEED_WORKDIR"
    --output-dir "$STRATEGIES_DIR/fuzz"
  )
  if [[ -n "$SYZ_DIR" ]]; then
    cmd+=(--syz-dir "$SYZ_DIR")
  fi
  if [[ -n "$fuzz_seconds" && "$fuzz_seconds" != "0" ]]; then
    cmd+=(--max-seconds "$fuzz_seconds")
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    cmd+=(--dry-run)
  fi
  cmd+=("$DISK_IMAGE" "$SSH_KEY" "$KERNEL_IMAGE")

  run_strategy_command fuzz "${cmd[@]}"
}

write_candidate_summary() {
  local finished_at
  finished_at="$(current_utc_timestamp)"

  "$PYTHON_BIN" - "$CANDIDATE_DIR" "$CANDIDATE_SOURCE" "$REQUESTED_STRATEGY" "$ARTIFACTS_ROOT" "$SUMMARY_PATH" \
    "$VERDICT_PATH" "$finished_at" "$TIMEOUT_SECONDS" "$DRY_RUN" <<'PY'
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

candidate_dir = Path(sys.argv[1])
candidate_source = sys.argv[2]
requested_strategy = sys.argv[3]
artifacts_root = sys.argv[4]
summary_path = Path(sys.argv[5])
top_level_verdict_path = Path(sys.argv[6])
finished_at = sys.argv[7]
timeout_seconds = int(sys.argv[8]) if sys.argv[8] else None
dry_run = sys.argv[9] == "1"

ranking = {
    "CONFIRMED": (5, 2),
    "UNRELATED_CRASH": (4, 1),
    "SETUP_FAILED": (3, 1),
    "TIMING_INCONCLUSIVE": (2, 1),
    "REACHED_NO_CRASH": (1, 0),
    "PATH_INFEASIBLE": (0, 0),
}
confidence_rank = {"high": 2, "medium": 1, "low": 0}

strategy_records = []
for path in sorted(candidate_dir.glob("strategies/*/orchestrator.json")):
    payload = json.loads(path.read_text(encoding="utf-8"))
    verdict_path = Path(payload["verdict_path"])
    verdict = None
    if verdict_path.is_file():
        verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    payload["verdict"] = verdict.get("verdict") if isinstance(verdict, dict) else None
    payload["confidence"] = verdict.get("confidence") if isinstance(verdict, dict) else None
    strategy_records.append(payload)

strategy_records.sort(key=lambda item: item["attempt_index"])

selected_record = None
for record in strategy_records:
    verdict = record.get("verdict")
    confidence = record.get("confidence")
    if verdict is None:
        continue
    candidate_weight = (
        ranking.get(verdict, (-1, -1))[0],
        confidence_rank.get(confidence or "", -1),
        -record["attempt_index"],
    )
    if selected_record is None:
        selected_record = dict(record)
        selected_record["_weight"] = candidate_weight
        continue
    if candidate_weight > selected_record["_weight"]:
        selected_record = dict(record)
        selected_record["_weight"] = candidate_weight

selected_strategy = None
final_verdict = None
final_confidence = None
if selected_record is not None:
    selected_strategy = selected_record["strategy"]
    selected_verdict_path = Path(selected_record["verdict_path"])
    if selected_verdict_path != top_level_verdict_path:
        shutil.copy2(selected_verdict_path, top_level_verdict_path)
    selected_payload = json.loads(top_level_verdict_path.read_text(encoding="utf-8"))
    final_verdict = selected_payload.get("verdict")
    final_confidence = selected_payload.get("confidence")
else:
    if top_level_verdict_path.is_file():
        selected_payload = json.loads(top_level_verdict_path.read_text(encoding="utf-8"))
        final_verdict = selected_payload.get("verdict")
        final_confidence = selected_payload.get("confidence")

artifacts = {
    "artifact_dir": str(candidate_dir),
    "artifacts_root": artifacts_root,
    "candidate": str(candidate_dir / "candidate.json"),
    "harness_source": str(candidate_dir / "harness.c") if (candidate_dir / "harness.c").is_file() else None,
    "mock_seed": str(candidate_dir / "mock_seed.json") if (candidate_dir / "mock_seed.json").is_file() else None,
    "seed_workdir": str(candidate_dir / "seed_workdir") if (candidate_dir / "seed_workdir").is_dir() else None,
    "summary": str(summary_path),
    "verdict": str(top_level_verdict_path) if top_level_verdict_path.is_file() else None,
    "witness_plan": str(candidate_dir / "witness_plan.json") if (candidate_dir / "witness_plan.json").is_file() else None,
    "witness_source": str(candidate_dir / "witness.syz") if (candidate_dir / "witness.syz").is_file() else None,
}

candidate_payload = json.loads((candidate_dir / "candidate.json").read_text(encoding="utf-8"))
plan_status = None
plan_path = candidate_dir / "witness_plan.json"
if plan_path.is_file():
    plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_status = plan_payload.get("status")

status = "completed"
if dry_run and final_verdict is None:
    status = "dry_run"
elif final_verdict is None:
    status = "failed"

payload = {
    "candidate_id": candidate_payload.get("candidate_id"),
    "candidate_source": candidate_source,
    "final_confidence": final_confidence,
    "final_verdict": final_verdict,
    "finished_at": finished_at,
    "plan_status": plan_status,
    "requested_strategy": requested_strategy,
    "selected_strategy": selected_strategy,
    "status": status,
    "strategies_attempted": strategy_records,
    "timeout_seconds": timeout_seconds,
    "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    "artifacts": artifacts,
}
summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

CANDIDATE_SOURCE=""
REQUESTED_STRATEGY="all"
ARTIFACTS_ROOT="$REPO_ROOT/verdicts"
TIMEOUT_SECONDS=""
TARGET_HOST=""
SSH_KEY=""
SSH_USER="root"
SSH_USER_EXPLICIT=0
SSH_PORT="22"
DISK_IMAGE=""
KERNEL_IMAGE=""
SYZ_DIR=""
WITNESS_RUNS="5"
TIMING_RANGE="0,100,1000,5000,10000,50000"
RUNS_PER_TIMING="10"
FUZZ_MAX_SECONDS=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --candidate)
      [[ $# -ge 2 ]] || usage
      CANDIDATE_SOURCE="$2"
      shift 2
      ;;
    --strategy)
      [[ $# -ge 2 ]] || usage
      REQUESTED_STRATEGY="$2"
      shift 2
      ;;
    --artifacts-root)
      [[ $# -ge 2 ]] || usage
      ARTIFACTS_ROOT="$2"
      shift 2
      ;;
    --timeout)
      [[ $# -ge 2 ]] || usage
      TIMEOUT_SECONDS="$2"
      shift 2
      ;;
    --target-host)
      [[ $# -ge 2 ]] || usage
      TARGET_HOST="$2"
      shift 2
      ;;
    --ssh-key)
      [[ $# -ge 2 ]] || usage
      SSH_KEY="$2"
      shift 2
      ;;
    --ssh-user)
      [[ $# -ge 2 ]] || usage
      SSH_USER="$2"
      SSH_USER_EXPLICIT=1
      shift 2
      ;;
    --ssh-port)
      [[ $# -ge 2 ]] || usage
      SSH_PORT="$2"
      shift 2
      ;;
    --disk-image)
      [[ $# -ge 2 ]] || usage
      DISK_IMAGE="$2"
      shift 2
      ;;
    --kernel-image)
      [[ $# -ge 2 ]] || usage
      KERNEL_IMAGE="$2"
      shift 2
      ;;
    --syz-dir)
      [[ $# -ge 2 ]] || usage
      SYZ_DIR="$2"
      shift 2
      ;;
    --witness-runs)
      [[ $# -ge 2 ]] || usage
      WITNESS_RUNS="$2"
      shift 2
      ;;
    --timing-range)
      [[ $# -ge 2 ]] || usage
      TIMING_RANGE="$2"
      shift 2
      ;;
    --runs-per-timing)
      [[ $# -ge 2 ]] || usage
      RUNS_PER_TIMING="$2"
      shift 2
      ;;
    --fuzz-max-seconds)
      [[ $# -ge 2 ]] || usage
      FUZZ_MAX_SECONDS="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      ;;
    --*)
      die "unknown option: $1"
      ;;
    *)
      usage
      ;;
  esac
done

[[ -n "$CANDIDATE_SOURCE" ]] || usage
case "$REQUESTED_STRATEGY" in
  harness|witness|fuzz|all) ;;
  *) die "unsupported strategy: $REQUESTED_STRATEGY" ;;
esac
[[ -z "$TIMEOUT_SECONDS" || "$TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] || die "timeout must be a positive integer"
[[ "$SSH_PORT" =~ ^[0-9]+$ ]] || die "ssh-port must be an integer"
[[ "$WITNESS_RUNS" =~ ^[1-9][0-9]*$ ]] || die "witness-runs must be a positive integer"
[[ "$RUNS_PER_TIMING" =~ ^[1-9][0-9]*$ ]] || die "runs-per-timing must be a positive integer"
[[ -z "$FUZZ_MAX_SECONDS" || "$FUZZ_MAX_SECONDS" =~ ^[1-9][0-9]*$ ]] || die "fuzz-max-seconds must be a positive integer"

require_cmd "$PYTHON_BIN"
require_file "$CANDIDATE_SOURCE" "candidate file not found: $CANDIDATE_SOURCE"
if [[ -z "${VERIFY_SOLVE_CANDIDATE_CMD:-}" || -z "${VERIFY_EMIT_WITNESS_CMD:-}" || -z "${VERIFY_GENERATE_HARNESS_CMD:-}" || -z "${VERIFY_EXPORT_MOCK_SEED_CMD:-}" ]]; then
  require_dir "$BRIDGE_ROOT" "bridge root not found: $BRIDGE_ROOT"
fi
if [[ -z "${VERIFY_IMPORT_SEED_CMD:-}" ]]; then
  require_file "$IMPORT_SEED_TOOL" "seed import tool not found: $IMPORT_SEED_TOOL"
fi

normalize_target_host

case "$REQUESTED_STRATEGY" in
  harness|witness)
    [[ -n "$TARGET_HOST" ]] || die "--target-host is required for strategy $REQUESTED_STRATEGY"
    [[ -n "$SSH_KEY" ]] || die "--ssh-key is required for strategy $REQUESTED_STRATEGY"
    ;;
  fuzz)
    [[ -n "$DISK_IMAGE" ]] || die "--disk-image is required for strategy fuzz"
    [[ -n "$SSH_KEY" ]] || die "--ssh-key is required for strategy fuzz"
    [[ -n "$KERNEL_IMAGE" ]] || die "--kernel-image is required for strategy fuzz"
    ;;
  all)
    [[ -n "$TARGET_HOST" ]] || die "--target-host is required for strategy all"
    [[ -n "$SSH_KEY" ]] || die "--ssh-key is required for strategy all"
    [[ -n "$DISK_IMAGE" ]] || die "--disk-image is required for strategy all"
    [[ -n "$KERNEL_IMAGE" ]] || die "--kernel-image is required for strategy all"
    ;;
esac

if [[ -n "$SSH_KEY" ]]; then
  require_file "$SSH_KEY" "ssh key not found: $SSH_KEY"
fi
if [[ -n "$DISK_IMAGE" ]]; then
  require_file "$DISK_IMAGE" "disk image not found: $DISK_IMAGE"
fi
if [[ -n "$KERNEL_IMAGE" ]]; then
  require_file "$KERNEL_IMAGE" "kernel image not found: $KERNEL_IMAGE"
fi
if [[ -n "$SYZ_DIR" ]]; then
  require_dir "$SYZ_DIR" "syz-dir not found: $SYZ_DIR"
fi

CANDIDATE_ID="$("$PYTHON_BIN" - "$CANDIDATE_SOURCE" <<'PY'
from pathlib import Path
import json
import sys

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
candidate_id = payload.get("candidate_id")
if not isinstance(candidate_id, str) or not candidate_id:
    raise SystemExit("candidate.json is missing candidate_id")
print(candidate_id)
PY
)"

CANDIDATE_DIR="$ARTIFACTS_ROOT/$CANDIDATE_ID"
LOG_DIR="$CANDIDATE_DIR/logs"
STRATEGIES_DIR="$CANDIDATE_DIR/strategies"
SEED_WORKDIR="$CANDIDATE_DIR/seed_workdir"
CANDIDATE_ARTIFACT="$CANDIDATE_DIR/candidate.json"
WITNESS_PLAN_PATH="$CANDIDATE_DIR/witness_plan.json"
WITNESS_SOURCE_PATH="$CANDIDATE_DIR/witness.syz"
HARNESS_SOURCE_PATH="$CANDIDATE_DIR/harness.c"
MOCK_SEED_PATH="$CANDIDATE_DIR/mock_seed.json"
VERDICT_PATH="$CANDIDATE_DIR/verdict.json"
SUMMARY_PATH="$CANDIDATE_DIR/summary.json"

mkdir -p "$CANDIDATE_DIR"
rm -rf "$LOG_DIR" "$STRATEGIES_DIR" "$SEED_WORKDIR"
rm -f "$WITNESS_PLAN_PATH" "$WITNESS_SOURCE_PATH" "$HARNESS_SOURCE_PATH" "$MOCK_SEED_PATH" "$VERDICT_PATH" "$SUMMARY_PATH"
mkdir -p "$LOG_DIR" "$STRATEGIES_DIR"
copy_candidate_into_artifact_dir

ATTEMPT_COUNTER=0
if [[ -n "$TIMEOUT_SECONDS" ]]; then
  TIMEOUT_DEADLINE=$(( $(date +%s) + TIMEOUT_SECONDS ))
else
  TIMEOUT_DEADLINE=0
fi

case "$REQUESTED_STRATEGY" in
  harness)
    run_harness_strategy || true
    ;;
  witness)
    run_witness_strategy || true
    ;;
  fuzz)
    run_fuzz_strategy || true
    ;;
  all)
    run_harness_strategy || true
    if [[ "$(strategy_verdict "$STRATEGIES_DIR/harness/verdict.json")" != "CONFIRMED" ]]; then
      run_witness_strategy || true
    fi
    if [[ "$(strategy_verdict "$STRATEGIES_DIR/harness/verdict.json")" != "CONFIRMED" && "$(strategy_verdict "$STRATEGIES_DIR/witness/verdict.json")" != "CONFIRMED" ]]; then
      run_fuzz_strategy || true
    fi
    ;;
esac

write_candidate_summary

if [[ -f "$VERDICT_PATH" ]]; then
  FINAL_VERDICT="$("$PYTHON_BIN" - "$VERDICT_PATH" <<'PY'
from pathlib import Path
import json
import sys

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload.get("verdict", ""))
PY
)"
  printf 'Final verdict: %s\n' "$FINAL_VERDICT"
else
  printf 'Final verdict: (none)\n'
fi
printf 'Candidate artifacts: %s\n' "$CANDIDATE_DIR"

if [[ -f "$VERDICT_PATH" || "$DRY_RUN" -eq 1 ]]; then
  exit 0
fi
exit 1
