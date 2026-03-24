#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
VERIFY_CANDIDATE_SCRIPT="${VERIFY_CANDIDATE_SCRIPT:-$REPO_ROOT/scripts/verify_candidate.sh}"

usage() {
  cat >&2 <<'EOF'
usage: verify_batch.sh --candidates-dir <path> [--strategy harness|witness|fuzz|all] [--artifacts-root <path>] [--timeout-per-candidate <seconds>] [--dry-run]
                       [--target-host <host>|<user@host>] [--ssh-key <path>] [--ssh-user <user>] [--ssh-port <port>]
                       [--disk-image <path>] [--kernel-image <path>] [--syz-dir <path>]
                       [--witness-runs <n>] [--timing-range <csv>] [--runs-per-timing <n>] [--fuzz-max-seconds <n>]
EOF
  exit 1
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

require_dir() {
  local path="$1"
  local message="$2"
  [[ -d "$path" ]] || die "$message"
}

require_file() {
  local path="$1"
  local message="$2"
  [[ -f "$path" ]] || die "$message"
}

CANDIDATES_DIR=""
REQUESTED_STRATEGY="all"
ARTIFACTS_ROOT="$REPO_ROOT/verdicts"
TIMEOUT_PER_CANDIDATE=""
TARGET_HOST=""
SSH_KEY=""
SSH_USER=""
SSH_PORT=""
DISK_IMAGE=""
KERNEL_IMAGE=""
SYZ_DIR=""
WITNESS_RUNS=""
TIMING_RANGE=""
RUNS_PER_TIMING=""
FUZZ_MAX_SECONDS=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --candidates-dir)
      [[ $# -ge 2 ]] || usage
      CANDIDATES_DIR="$2"
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
    --timeout-per-candidate)
      [[ $# -ge 2 ]] || usage
      TIMEOUT_PER_CANDIDATE="$2"
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

[[ -n "$CANDIDATES_DIR" ]] || usage
case "$REQUESTED_STRATEGY" in
  harness|witness|fuzz|all) ;;
  *) die "unsupported strategy: $REQUESTED_STRATEGY" ;;
esac
[[ -z "$TIMEOUT_PER_CANDIDATE" || "$TIMEOUT_PER_CANDIDATE" =~ ^[1-9][0-9]*$ ]] || die "timeout-per-candidate must be a positive integer"

require_cmd "$PYTHON_BIN"
require_dir "$CANDIDATES_DIR" "candidates directory not found: $CANDIDATES_DIR"
require_file "$VERIFY_CANDIDATE_SCRIPT" "verify_candidate.sh not found: $VERIFY_CANDIDATE_SCRIPT"

mkdir -p "$ARTIFACTS_ROOT/batch-logs"
MANIFEST_PATH="$ARTIFACTS_ROOT/batch-results.tsv"
SUMMARY_PATH="$ARTIFACTS_ROOT/summary.json"
rm -f "$MANIFEST_PATH" "$SUMMARY_PATH"

candidate_count=0
while IFS=$'\t' read -r candidate_id candidate_path; do
  [[ -n "$candidate_id" ]] || continue
  candidate_count=$((candidate_count + 1))

  stdout_log="$ARTIFACTS_ROOT/batch-logs/${candidate_id}.stdout.log"
  stderr_log="$ARTIFACTS_ROOT/batch-logs/${candidate_id}.stderr.log"

  cmd=(bash "$VERIFY_CANDIDATE_SCRIPT" --candidate "$candidate_path" --strategy "$REQUESTED_STRATEGY" --artifacts-root "$ARTIFACTS_ROOT")
  if [[ -n "$TIMEOUT_PER_CANDIDATE" ]]; then
    cmd+=(--timeout "$TIMEOUT_PER_CANDIDATE")
  fi
  if [[ -n "$TARGET_HOST" ]]; then
    cmd+=(--target-host "$TARGET_HOST")
  fi
  if [[ -n "$SSH_KEY" ]]; then
    cmd+=(--ssh-key "$SSH_KEY")
  fi
  if [[ -n "$SSH_USER" ]]; then
    cmd+=(--ssh-user "$SSH_USER")
  fi
  if [[ -n "$SSH_PORT" ]]; then
    cmd+=(--ssh-port "$SSH_PORT")
  fi
  if [[ -n "$DISK_IMAGE" ]]; then
    cmd+=(--disk-image "$DISK_IMAGE")
  fi
  if [[ -n "$KERNEL_IMAGE" ]]; then
    cmd+=(--kernel-image "$KERNEL_IMAGE")
  fi
  if [[ -n "$SYZ_DIR" ]]; then
    cmd+=(--syz-dir "$SYZ_DIR")
  fi
  if [[ -n "$WITNESS_RUNS" ]]; then
    cmd+=(--witness-runs "$WITNESS_RUNS")
  fi
  if [[ -n "$TIMING_RANGE" ]]; then
    cmd+=(--timing-range "$TIMING_RANGE")
  fi
  if [[ -n "$RUNS_PER_TIMING" ]]; then
    cmd+=(--runs-per-timing "$RUNS_PER_TIMING")
  fi
  if [[ -n "$FUZZ_MAX_SECONDS" ]]; then
    cmd+=(--fuzz-max-seconds "$FUZZ_MAX_SECONDS")
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    cmd+=(--dry-run)
  fi

  set +e
  "${cmd[@]}" >"$stdout_log" 2>"$stderr_log"
  rc=$?
  set -e

  printf '%s\t%s\t%s\t%s\t%s\n' \
    "$candidate_id" \
    "$candidate_path" \
    "$rc" \
    "$ARTIFACTS_ROOT/$candidate_id/summary.json" \
    "$ARTIFACTS_ROOT/$candidate_id/verdict.json" >>"$MANIFEST_PATH"
done < <("$PYTHON_BIN" - "$CANDIDATES_DIR" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

candidates_dir = Path(sys.argv[1])
seen: dict[str, Path] = {}
rows: list[tuple[str, Path]] = []
for path in sorted(candidates_dir.glob("*.json")):
    candidate_id = path.stem
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    if isinstance(payload, dict) and isinstance(payload.get("candidate_id"), str) and payload.get("candidate_id"):
        candidate_id = payload["candidate_id"]
    previous = seen.get(candidate_id)
    if previous is not None and previous != path:
        raise SystemExit(f"duplicate candidate_id in batch: {candidate_id}")
    seen[candidate_id] = path
    rows.append((candidate_id, path.resolve()))
for candidate_id, path in rows:
    print(f"{candidate_id}\t{path}")
PY
)

[[ "$candidate_count" -gt 0 ]] || die "no candidate JSON files found under $CANDIDATES_DIR"

"$PYTHON_BIN" - "$MANIFEST_PATH" "$SUMMARY_PATH" "$ARTIFACTS_ROOT" "$CANDIDATES_DIR" "$REQUESTED_STRATEGY" "$TIMEOUT_PER_CANDIDATE" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

manifest_path = Path(sys.argv[1])
summary_path = Path(sys.argv[2])
artifacts_root = sys.argv[3]
candidates_dir = sys.argv[4]
requested_strategy = sys.argv[5]
timeout_per_candidate = int(sys.argv[6]) if sys.argv[6] else None

counts = {
    "COMMAND_FAILED": 0,
    "CONFIRMED": 0,
    "NO_VERDICT": 0,
    "PATH_INFEASIBLE": 0,
    "REACHED_NO_CRASH": 0,
    "SETUP_FAILED": 0,
    "TIMING_INCONCLUSIVE": 0,
    "UNRELATED_CRASH": 0,
}
candidates = []

for line in manifest_path.read_text(encoding="utf-8").splitlines():
    if not line:
        continue
    candidate_id, candidate_source, exit_code_text, summary_file, verdict_file = line.split("\t")
    exit_code = int(exit_code_text)
    summary_payload = None
    verdict_payload = None
    summary_path_for_candidate = Path(summary_file)
    verdict_path_for_candidate = Path(verdict_file)
    if summary_path_for_candidate.is_file():
        summary_payload = json.loads(summary_path_for_candidate.read_text(encoding="utf-8"))
    if verdict_path_for_candidate.is_file():
        verdict_payload = json.loads(verdict_path_for_candidate.read_text(encoding="utf-8"))

    final_verdict = None
    selected_strategy = None
    status = "failed"
    if isinstance(summary_payload, dict):
        final_verdict = summary_payload.get("final_verdict")
        selected_strategy = summary_payload.get("selected_strategy")
        status = summary_payload.get("status", status)
    elif isinstance(verdict_payload, dict):
        final_verdict = verdict_payload.get("verdict")
        status = "completed"

    if final_verdict in counts:
        counts[final_verdict] += 1
    else:
        counts["NO_VERDICT"] += 1
        if exit_code != 0:
            counts["COMMAND_FAILED"] += 1

    candidates.append(
        {
            "candidate_id": candidate_id,
            "candidate_source": candidate_source,
            "exit_code": exit_code,
            "final_verdict": final_verdict,
            "selected_strategy": selected_strategy,
            "status": status,
            "summary_path": summary_file if summary_path_for_candidate.is_file() else None,
            "verdict_path": verdict_file if verdict_path_for_candidate.is_file() else None,
        }
    )

payload = {
    "artifacts_root": artifacts_root,
    "batch_version": "verify_batch/v1",
    "candidates": candidates,
    "candidates_dir": candidates_dir,
    "candidates_total": len(candidates),
    "counts": counts,
    "requested_strategy": requested_strategy,
    "timeout_per_candidate": timeout_per_candidate,
    "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
}
summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

printf 'Batch summary: %s\n' "$SUMMARY_PATH"

if "$PYTHON_BIN" - "$MANIFEST_PATH" <<'PY'
from pathlib import Path
import sys

for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if not line:
        continue
    exit_code = int(line.split("\t")[2])
    if exit_code != 0:
        raise SystemExit(1)
PY
then
  exit 0
fi
exit 1
