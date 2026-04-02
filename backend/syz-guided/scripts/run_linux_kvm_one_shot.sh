#!/usr/bin/env bash
# run_linux_kvm_one_shot.sh — One-shot seed execution under QEMU/KVM on Linux.
#
# Implements section 5 of plans/linux-kvm-runbook.md:
#   boot guest → verify /dev/kvm → copy binaries → run one seed → collect logs → shutdown.
#
# This is intentionally narrower than a syz-manager campaign.
# No mutation, no coverage loop, no campaign logic.
#
# Usage:
#   bash run_linux_kvm_one_shot.sh \
#     --kernel <path>        # arm64 kernel Image
#     --disk <path>          # arm64 guest disk (qcow2)
#     --ssh-key <path>       # SSH private key for guest
#     --syz-execprog <path>  # syz-execprog binary (linux/arm64)
#     --syz-executor <path>  # syz-executor binary (linux/arm64)
#     --prog <path>          # .prog seed file
#     --out-dir <path>       # output directory for logs
#     [--ssh-port 10022]     # SSH forwarding port (default: 10022)
#     [--mem 2048]           # guest memory in MiB (default: 2048)
#     [--boot-timeout 60]    # seconds to wait for SSH (default: 60)
#
# Exit codes:
#   0  Seed executed, logs collected
#   1  Hard blocker or runtime failure
set -euo pipefail

# ── Defaults ──

SSH_PORT=10022
MEM=2048
BOOT_TIMEOUT=60
QEMU_PID=""

# ── Parse arguments ──

KERNEL="" DISK="" SSH_KEY="" SYZ_EXECPROG="" SYZ_EXECUTOR="" PROG="" OUT_DIR=""

usage() {
    echo "Usage: $0 --kernel <path> --disk <path> --ssh-key <path> \\"
    echo "         --syz-execprog <path> --syz-executor <path> --prog <path> \\"
    echo "         --out-dir <path> [--ssh-port 10022] [--mem 2048] [--boot-timeout 60]"
    echo ""
    echo "One-shot arm64 seed execution under QEMU/KVM on a Linux host."
    echo "See plans/linux-kvm-runbook.md section 5 for context."
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --kernel)       KERNEL="$2";       shift 2 ;;
        --disk)         DISK="$2";         shift 2 ;;
        --ssh-key)      SSH_KEY="$2";      shift 2 ;;
        --syz-execprog) SYZ_EXECPROG="$2"; shift 2 ;;
        --syz-executor) SYZ_EXECUTOR="$2"; shift 2 ;;
        --prog)         PROG="$2";         shift 2 ;;
        --out-dir)      OUT_DIR="$2";      shift 2 ;;
        --ssh-port)     SSH_PORT="$2";     shift 2 ;;
        --mem)          MEM="$2";          shift 2 ;;
        --boot-timeout) BOOT_TIMEOUT="$2"; shift 2 ;;
        -h|--help)      usage; exit 0 ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

# ── Helpers ──

log()  { echo "[one-shot] $1"; }
fail() { echo "[one-shot] FAIL: $1" >&2; exit 1; }

ssh_cmd() {
    ssh -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -o ConnectTimeout=5 \
        -o LogLevel=ERROR \
        -i "$SSH_KEY" \
        -p "$SSH_PORT" \
        root@127.0.0.1 "$@"
}

scp_cmd() {
    scp -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -o LogLevel=ERROR \
        -i "$SSH_KEY" \
        -P "$SSH_PORT" \
        "$@"
}

# ── Cleanup trap ──

cleanup() {
    if [[ -n "$QEMU_PID" ]] && kill -0 "$QEMU_PID" 2>/dev/null; then
        log "Shutting down VM (pid $QEMU_PID)..."
        # Try graceful SSH poweroff.
        ssh_cmd poweroff 2>/dev/null || true
        local waited=0
        while kill -0 "$QEMU_PID" 2>/dev/null && [[ $waited -lt 15 ]]; do
            sleep 1
            waited=$((waited + 1))
        done
        # SIGTERM fallback.
        if kill -0 "$QEMU_PID" 2>/dev/null; then
            kill "$QEMU_PID" 2>/dev/null || true
            sleep 2
        fi
        # SIGKILL last resort.
        if kill -0 "$QEMU_PID" 2>/dev/null; then
            kill -9 "$QEMU_PID" 2>/dev/null || true
        fi
        wait "$QEMU_PID" 2>/dev/null || true
        log "VM stopped."
    fi
}
trap cleanup EXIT

# ══════════════════════════════════════════════════
# Step 1: Validate arguments and host prerequisites
# ══════════════════════════════════════════════════

log "Validating prerequisites..."

# Required arguments.
[[ -z "$KERNEL" ]]       && fail "--kernel is required"
[[ -z "$DISK" ]]         && fail "--disk is required"
[[ -z "$SSH_KEY" ]]      && fail "--ssh-key is required"
[[ -z "$SYZ_EXECPROG" ]] && fail "--syz-execprog is required"
[[ -z "$SYZ_EXECUTOR" ]] && fail "--syz-executor is required"
[[ -z "$PROG" ]]         && fail "--prog is required"
[[ -z "$OUT_DIR" ]]      && fail "--out-dir is required"

# Host must be Linux.
[[ "$(uname -s)" != "Linux" ]] && fail "This script requires a Linux host (current: $(uname -s))"

# /dev/kvm must exist and be writable.
[[ ! -e /dev/kvm ]] && fail "/dev/kvm does not exist — is KVM module loaded?"
[[ ! -w /dev/kvm ]] && fail "/dev/kvm is not writable by $(whoami)"

# QEMU must be available.
command -v qemu-system-aarch64 >/dev/null 2>&1 || fail "qemu-system-aarch64 not found in PATH"

# All file paths must exist.
[[ ! -f "$KERNEL" ]]       && fail "Kernel image not found: $KERNEL"
[[ ! -f "$DISK" ]]         && fail "Disk image not found: $DISK"
[[ ! -f "$SSH_KEY" ]]      && fail "SSH key not found: $SSH_KEY"
[[ ! -f "$SYZ_EXECPROG" ]] && fail "syz-execprog not found: $SYZ_EXECPROG"
[[ ! -f "$SYZ_EXECUTOR" ]] && fail "syz-executor not found: $SYZ_EXECUTOR"
[[ ! -f "$PROG" ]]         && fail "Prog file not found: $PROG"

mkdir -p "$OUT_DIR"
log "Prerequisites OK."

# ══════════════════════════════════════════════════
# Step 2: Launch guest with QEMU/KVM
# ══════════════════════════════════════════════════

CONSOLE_LOG="$OUT_DIR/qemu-console.log"

log "Booting QEMU/KVM (ssh_port=$SSH_PORT, mem=${MEM}M)..."

qemu-system-aarch64 \
    -machine virt \
    -accel kvm \
    -cpu host \
    -m "$MEM" \
    -nographic \
    -kernel "$KERNEL" \
    -drive "if=virtio,format=qcow2,file=$DISK" \
    -append "root=/dev/vda1 console=ttyAMA0 kasan.fault=panic" \
    -netdev "user,id=net0,hostfwd=tcp:127.0.0.1:${SSH_PORT}-:22" \
    -device virtio-net-pci,netdev=net0 \
    -no-reboot \
    -serial "file:$CONSOLE_LOG" &

QEMU_PID=$!
sleep 1

# Verify QEMU started.
if ! kill -0 "$QEMU_PID" 2>/dev/null; then
    fail "QEMU exited immediately — check $CONSOLE_LOG"
fi

log "QEMU started (pid $QEMU_PID)."

# ══════════════════════════════════════════════════
# Step 3: Wait for SSH
# ══════════════════════════════════════════════════

log "Waiting for SSH (timeout ${BOOT_TIMEOUT}s)..."

SSH_READY=0
WAITED=0
while [[ $WAITED -lt $BOOT_TIMEOUT ]]; do
    if ssh_cmd true 2>/dev/null; then
        SSH_READY=1
        break
    fi
    sleep 2
    WAITED=$((WAITED + 2))
done

if [[ $SSH_READY -eq 0 ]]; then
    fail "SSH not ready after ${BOOT_TIMEOUT}s — guest may not have booted. Check $CONSOLE_LOG"
fi

log "SSH ready after ~${WAITED}s."

# ══════════════════════════════════════════════════
# Step 4: Verify /dev/kvm inside guest
# ══════════════════════════════════════════════════

log "Checking /dev/kvm inside guest..."

KVM_CHECK_FILE="$OUT_DIR/guest-kvm-check.txt"
ssh_cmd 'ls -la /dev/kvm 2>&1; echo "exit_code=$?"' > "$KVM_CHECK_FILE" 2>&1

if grep -q "exit_code=0" "$KVM_CHECK_FILE"; then
    log "Guest /dev/kvm: available."
else
    log "FAIL: /dev/kvm not available inside guest. See $KVM_CHECK_FILE"
    cat "$KVM_CHECK_FILE"
    fail "Guest /dev/kvm is missing — kernel may lack CONFIG_KVM=y"
fi

# ══════════════════════════════════════════════════
# Step 5: Copy binaries and seed into guest
# ══════════════════════════════════════════════════

log "Copying syz-execprog, syz-executor, and $(basename "$PROG") into guest..."

scp_cmd "$SYZ_EXECPROG" root@127.0.0.1:/root/syz-execprog
scp_cmd "$SYZ_EXECUTOR" root@127.0.0.1:/root/syz-executor
scp_cmd "$PROG"         root@127.0.0.1:/root/seed.prog

ssh_cmd 'chmod +x /root/syz-execprog /root/syz-executor'

log "Binaries and seed copied."

# ══════════════════════════════════════════════════
# Step 6: Run exactly one execution
# ══════════════════════════════════════════════════

EXECPROG_LOG="$OUT_DIR/execprog.log"
PROG_NAME=$(basename "$PROG")

log "Running syz-execprog with $PROG_NAME..."

# -repeat=0 means run each program once then exit.
# -slowdown=1 is correct for KVM (TCG needed 10).
ssh_cmd 'cd /root && ./syz-execprog -executor=./syz-executor -repeat=0 -procs=1 -slowdown=1 seed.prog 2>&1' \
    > "$EXECPROG_LOG" 2>&1 || true

EXEC_LINES=$(wc -l < "$EXECPROG_LOG" | tr -d ' ')
log "syz-execprog finished ($EXEC_LINES lines captured in execprog.log)."

# ══════════════════════════════════════════════════
# Step 7: Collect guest logs
# ══════════════════════════════════════════════════

DMESG_LOG="$OUT_DIR/dmesg.log"

log "Collecting dmesg..."
ssh_cmd dmesg > "$DMESG_LOG" 2>&1 || true

DMESG_LINES=$(wc -l < "$DMESG_LOG" | tr -d ' ')
log "dmesg collected ($DMESG_LINES lines)."

# Check for KASAN reports.
KASAN_COUNT=$(grep -c "BUG: KASAN" "$DMESG_LOG" 2>/dev/null || echo "0")

# ══════════════════════════════════════════════════
# Step 8: Write run summary
# ══════════════════════════════════════════════════

SUMMARY="$OUT_DIR/run-summary.txt"

{
    echo "=== run_linux_kvm_one_shot summary ==="
    echo "Date:           $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "Host:           $(uname -a)"
    echo "Kernel image:   $KERNEL"
    echo "Disk image:     $DISK"
    echo "Prog:           $PROG"
    echo "SSH port:       $SSH_PORT"
    echo "Boot wait:      ~${WAITED}s"
    echo "Guest /dev/kvm: $(grep -q 'exit_code=0' "$KVM_CHECK_FILE" && echo 'available' || echo 'MISSING')"
    echo "execprog lines: $EXEC_LINES"
    echo "dmesg lines:    $DMESG_LINES"
    echo "KASAN reports:  $KASAN_COUNT"
    echo ""
    echo "Output files:"
    echo "  $CONSOLE_LOG"
    echo "  $KVM_CHECK_FILE"
    echo "  $EXECPROG_LOG"
    echo "  $DMESG_LOG"
    echo "  $SUMMARY"
} > "$SUMMARY"

# ── Final status ──
# The cleanup trap handles VM shutdown.

log "Done. Output in $OUT_DIR"
if [[ "$KASAN_COUNT" -gt 0 ]]; then
    log "KASAN detected ($KASAN_COUNT report(s)) — run triage pipeline next."
else
    log "No KASAN reports in dmesg."
fi

cat "$SUMMARY"
