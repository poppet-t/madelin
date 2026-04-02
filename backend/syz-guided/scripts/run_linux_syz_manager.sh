#!/usr/bin/env bash
# run_linux_syz_manager.sh — Launch a bounded syz-manager campaign on a Linux KVM host.
#
# Implements section 6 of plans/linux-kvm-runbook.md:
#   verify host → verify syzkaller binaries → launch syz-manager → capture logs.
#
# This script does NOT boot a VM manually — syz-manager manages the VM lifecycle
# in QEMU mode, or connects to a pre-booted VM in isolated mode.
# It does NOT parse results or run triage — those are separate steps.
#
# Usage:
#   bash run_linux_syz_manager.sh \
#     --config <path>      # syz-manager config file (JSON)
#     --out-dir <path>     # output directory for logs
#     [--syz-dir <path>]   # syzkaller root (default: $SYZ_DIR or auto-detect from repo)
#     [--timeout 600]      # campaign timeout in seconds (0 = no limit, default: 600)
#
# Exit codes:
#   0  syz-manager ran and exited normally
#   1  Hard blocker or runtime failure
#   124  syz-manager killed by timeout
set -euo pipefail

# ── Defaults ──

CONFIG=""
OUT_DIR=""
TIMEOUT=600
SYZ_DIR_ARG=""

# ── Parse arguments ──

usage() {
    echo "Usage: $0 --config <path> --out-dir <path> [--syz-dir <path>] [--timeout 600]"
    echo ""
    echo "Launch a bounded syz-manager campaign on a Linux KVM host."
    echo "See plans/linux-kvm-runbook.md section 6 for context."
    echo ""
    echo "Options:"
    echo "  --config    Path to syz-manager config file (JSON)"
    echo "  --out-dir   Output directory for logs and summary"
    echo "  --syz-dir   Syzkaller root directory (default: \$SYZ_DIR env var)"
    echo "  --timeout   Campaign timeout in seconds (0 = no limit, default: 600)"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)  CONFIG="$2";      shift 2 ;;
        --out-dir) OUT_DIR="$2";     shift 2 ;;
        --syz-dir) SYZ_DIR_ARG="$2"; shift 2 ;;
        --timeout) TIMEOUT="$2";     shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

# ── Helpers ──

log()  { echo "[syz-manager] $1"; }
fail() { echo "[syz-manager] FAIL: $1" >&2; exit 1; }

# ── Resolve SYZ_DIR ──

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(cd "$BACKEND_DIR/../.." && pwd)"

if [[ -n "$SYZ_DIR_ARG" ]]; then
    RESOLVED_SYZ_DIR="$SYZ_DIR_ARG"
elif [[ -n "${SYZ_DIR:-}" ]]; then
    RESOLVED_SYZ_DIR="$SYZ_DIR"
elif [[ -d "$REPO_ROOT/syzkaller" ]]; then
    RESOLVED_SYZ_DIR="$REPO_ROOT/syzkaller"
else
    fail "No syzkaller directory found. Set --syz-dir, \$SYZ_DIR, or ensure syzkaller/ exists in repo root."
fi

# ══════════════════════════════════════════════════
# Step 1: Validate host prerequisites
# ══════════════════════════════════════════════════

log "Validating prerequisites..."

# Required arguments.
[[ -z "$CONFIG" ]]  && fail "--config is required"
[[ -z "$OUT_DIR" ]] && fail "--out-dir is required"

# Host must be Linux.
[[ "$(uname -s)" != "Linux" ]] && fail "This script requires a Linux host (current: $(uname -s))"

# /dev/kvm must exist and be writable.
[[ ! -e /dev/kvm ]] && fail "/dev/kvm does not exist — is KVM module loaded?"
[[ ! -w /dev/kvm ]] && fail "/dev/kvm is not writable by $(whoami)"

# QEMU must be available.
command -v qemu-system-aarch64 >/dev/null 2>&1 || fail "qemu-system-aarch64 not found in PATH"

# ══════════════════════════════════════════════════
# Step 2: Validate syzkaller binaries
# ══════════════════════════════════════════════════

log "Checking syzkaller binaries in $RESOLVED_SYZ_DIR..."

# syz-manager runs on the host — it's at bin/syz-manager.
SYZ_MANAGER="$RESOLVED_SYZ_DIR/bin/syz-manager"
if [[ ! -x "$SYZ_MANAGER" ]]; then
    # Some builds put it directly in bin/.
    if [[ -x "$RESOLVED_SYZ_DIR/bin/linux_arm64/syz-manager" ]]; then
        SYZ_MANAGER="$RESOLVED_SYZ_DIR/bin/linux_arm64/syz-manager"
    else
        fail "syz-manager not found at $RESOLVED_SYZ_DIR/bin/syz-manager — run 'make' in syzkaller/"
    fi
fi

# Guest binaries — syz-manager copies these into the VM.
SYZ_EXECPROG="$RESOLVED_SYZ_DIR/bin/linux_arm64/syz-execprog"
SYZ_EXECUTOR="$RESOLVED_SYZ_DIR/bin/linux_arm64/syz-executor"

[[ ! -f "$SYZ_EXECPROG" ]] && fail "syz-execprog not found at $SYZ_EXECPROG"
[[ ! -f "$SYZ_EXECUTOR" ]] && fail "syz-executor not found at $SYZ_EXECUTOR"

log "syz-manager:  $SYZ_MANAGER"
log "syz-execprog: $SYZ_EXECPROG"
log "syz-executor: $SYZ_EXECUTOR"

# ══════════════════════════════════════════════════
# Step 3: Validate config
# ══════════════════════════════════════════════════

[[ ! -f "$CONFIG" ]] && fail "Config file not found: $CONFIG"
[[ ! -r "$CONFIG" ]] && fail "Config file not readable: $CONFIG"

log "Config: $CONFIG"

# ══════════════════════════════════════════════════
# Step 4: Create output directory and launch
# ══════════════════════════════════════════════════

mkdir -p "$OUT_DIR"

MANAGER_LOG="$OUT_DIR/syz-manager.log"
SUMMARY="$OUT_DIR/run-summary.txt"

log "Launching syz-manager (timeout=${TIMEOUT}s)..."
log "Log: $MANAGER_LOG"

START_TIME=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
EXIT_CODE=0

if [[ "$TIMEOUT" -gt 0 ]]; then
    # Use timeout command for bounded execution.
    timeout --signal=SIGINT --kill-after=30 "$TIMEOUT" \
        "$SYZ_MANAGER" -config "$CONFIG" \
        > >(tee "$MANAGER_LOG") 2>&1 \
        || EXIT_CODE=$?
else
    "$SYZ_MANAGER" -config "$CONFIG" \
        > >(tee "$MANAGER_LOG") 2>&1 \
        || EXIT_CODE=$?
fi

END_TIME=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

# timeout exits 124 on timeout, 137 on SIGKILL.
case $EXIT_CODE in
    0)   EXIT_REASON="clean_exit" ;;
    124) EXIT_REASON="timeout" ;;
    137) EXIT_REASON="killed" ;;
    *)   EXIT_REASON="error (code $EXIT_CODE)" ;;
esac

log "syz-manager exited: $EXIT_REASON"

# ══════════════════════════════════════════════════
# Step 5: Write run summary
# ══════════════════════════════════════════════════

LOG_LINES=$(wc -l < "$MANAGER_LOG" 2>/dev/null | tr -d ' ' || echo "0")

{
    echo "=== run_linux_syz_manager summary ==="
    echo "Date start:     $START_TIME"
    echo "Date end:       $END_TIME"
    echo "Host:           $(uname -a)"
    echo "Config:         $CONFIG"
    echo "SYZ_DIR:        $RESOLVED_SYZ_DIR"
    echo "syz-manager:    $SYZ_MANAGER"
    echo "Timeout:        ${TIMEOUT}s"
    echo "Exit reason:    $EXIT_REASON"
    echo "Exit code:      $EXIT_CODE"
    echo "Log lines:      $LOG_LINES"
    echo ""
    echo "Output files:"
    echo "  $MANAGER_LOG"
    echo "  $SUMMARY"
    echo ""
    echo "Next steps:"
    echo "  - Check $MANAGER_LOG for crash reports"
    echo "  - Look for crash artifacts in the syz-manager workdir"
    echo "  - Run candidate-aware triage on any crash logs"
} > "$SUMMARY"

cat "$SUMMARY"

# Exit 124 for timeout, preserve original exit code otherwise.
if [[ $EXIT_CODE -eq 124 ]]; then
    exit 124
fi
exit $EXIT_CODE
