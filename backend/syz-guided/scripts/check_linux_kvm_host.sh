#!/usr/bin/env bash
# check_linux_kvm_host.sh — Verify a Linux host is ready for arm64 KVM validation.
#
# Checks host prerequisites from plans/linux-kvm-runbook.md sections 1-2.
# Prints a PASS / WARN / FAIL summary per check; exits nonzero on hard blockers.
#
# Usage:
#   bash check_linux_kvm_host.sh [--kernel <path>] [--disk <path>] [--ssh-key <path>]
#
# Or via environment variables:
#   VM_KERNEL=/path/to/Image VM_DISK=/path/to/disk.qcow2 VM_SSH_KEY=/path/to/id_rsa \
#     bash check_linux_kvm_host.sh
#
# Exit codes:
#   0  All hard checks pass (some warnings allowed)
#   1  One or more hard checks failed
set -euo pipefail

# ── Parse arguments ──

KERNEL="${VM_KERNEL:-}"
DISK="${VM_DISK:-}"
SSH_KEY="${VM_SSH_KEY:-}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --kernel)  KERNEL="$2"; shift 2 ;;
        --disk)    DISK="$2"; shift 2 ;;
        --ssh-key) SSH_KEY="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--kernel <path>] [--disk <path>] [--ssh-key <path>]"
            echo ""
            echo "Checks whether this Linux host is ready for arm64 KVM validation."
            echo "Asset paths can also be set via VM_KERNEL, VM_DISK, VM_SSH_KEY env vars."
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            echo "Run $0 --help for usage." >&2
            exit 1
            ;;
    esac
done

# ── Counters ──

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

pass() { echo "  [PASS] $1"; PASS_COUNT=$((PASS_COUNT + 1)); }
warn() { echo "  [WARN] $1"; WARN_COUNT=$((WARN_COUNT + 1)); }
fail() { echo "  [FAIL] $1"; FAIL_COUNT=$((FAIL_COUNT + 1)); }

# ── Detect repo root ──

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(cd "$BACKEND_DIR/../.." && pwd)"

echo "=== check_linux_kvm_host ==="
echo "Repo root: $REPO_ROOT"
echo ""

# ── 1. Host OS ──

echo "--- Host OS ---"
if [[ "$(uname -s)" == "Linux" ]]; then
    pass "Host is Linux ($(uname -r))"
else
    fail "Host is $(uname -s), not Linux — KVM requires a Linux host"
fi

# ── 2. /dev/kvm ──

echo "--- KVM device ---"
if [[ -e /dev/kvm ]]; then
    pass "/dev/kvm exists"
    if [[ -w /dev/kvm ]]; then
        pass "/dev/kvm is writable by current user ($(whoami))"
    else
        fail "/dev/kvm exists but is not writable by $(whoami) — check group membership (usually 'kvm')"
    fi
else
    fail "/dev/kvm does not exist — check that KVM module is loaded (modprobe kvm)"
fi

# ── 3. QEMU ──

echo "--- QEMU ---"
if command -v qemu-system-aarch64 >/dev/null 2>&1; then
    QEMU_VERSION=$(qemu-system-aarch64 --version 2>&1 | head -1 || true)
    pass "qemu-system-aarch64 found: $QEMU_VERSION"
else
    fail "qemu-system-aarch64 not found in PATH"
fi

# ── 4. Go toolchain ──

echo "--- Go ---"
if command -v go >/dev/null 2>&1; then
    GO_VERSION=$(go version 2>&1 || true)
    pass "go found: $GO_VERSION"
else
    warn "go not found in PATH — needed to build syzkaller from source"
fi

# ── 5. Syzkaller source tree ──

echo "--- Syzkaller source ---"
if [[ -d "$REPO_ROOT/syzkaller" ]] && [[ -f "$REPO_ROOT/syzkaller/Makefile" ]]; then
    pass "syzkaller/ directory exists with Makefile"
else
    fail "syzkaller/ directory not found at $REPO_ROOT/syzkaller — expected in-repo checkout"
fi

# ── 6. Runtime assets (optional) ──

echo "--- Runtime assets ---"

check_asset() {
    local label="$1"
    local path="$2"

    if [[ -z "$path" ]]; then
        warn "$label not specified (use --$(echo "$label" | tr 'A-Z' 'a-z') or set env var)"
        return
    fi
    if [[ ! -e "$path" ]]; then
        fail "$label path does not exist: $path"
        return
    fi
    if [[ ! -f "$path" ]]; then
        fail "$label path is not a regular file: $path"
        return
    fi
    if [[ ! -s "$path" ]]; then
        fail "$label file is empty: $path"
        return
    fi
    local size
    size=$(stat --format='%s' "$path" 2>/dev/null || stat -f '%z' "$path" 2>/dev/null || echo "unknown")
    pass "$label exists ($size bytes): $path"
}

check_asset "kernel" "$KERNEL"
check_asset "disk" "$DISK"

if [[ -n "$SSH_KEY" ]]; then
    if [[ ! -e "$SSH_KEY" ]]; then
        fail "ssh-key path does not exist: $SSH_KEY"
    elif [[ ! -f "$SSH_KEY" ]]; then
        fail "ssh-key path is not a regular file: $SSH_KEY"
    elif [[ ! -s "$SSH_KEY" ]]; then
        fail "ssh-key file is empty: $SSH_KEY"
    else
        # Check permissions — SSH key should not be world/group readable.
        PERMS=$(stat --format='%a' "$SSH_KEY" 2>/dev/null || stat -f '%Lp' "$SSH_KEY" 2>/dev/null || echo "unknown")
        if [[ "$PERMS" == "600" ]] || [[ "$PERMS" == "400" ]]; then
            pass "ssh-key exists (mode $PERMS): $SSH_KEY"
        else
            warn "ssh-key exists but has mode $PERMS (expected 600 or 400): $SSH_KEY"
        fi
    fi
else
    warn "ssh-key not specified (pass --ssh-key or set VM_SSH_KEY)"
fi

# ── 7. Backend fixtures ──

echo "--- Backend fixtures ---"
FIXTURES="$BACKEND_DIR/tests/fixtures"
if [[ -f "$FIXTURES/candidate.json" ]] && [[ -f "$FIXTURES/witness_plan.json" ]]; then
    pass "Bridge fixture artifacts present (candidate.json, witness_plan.json)"
else
    warn "Bridge fixture artifacts not found at $FIXTURES"
fi

# ── Summary ──

echo ""
echo "=== Summary ==="
echo "  PASS: $PASS_COUNT"
echo "  WARN: $WARN_COUNT"
echo "  FAIL: $FAIL_COUNT"

if [[ $FAIL_COUNT -gt 0 ]]; then
    echo ""
    echo "RESULT: NOT READY — $FAIL_COUNT hard blocker(s) found."
    echo "See plans/linux-kvm-runbook.md for resolution steps."
    exit 1
else
    echo ""
    if [[ $WARN_COUNT -gt 0 ]]; then
        echo "RESULT: READY (with $WARN_COUNT warning(s) — review above)"
    else
        echo "RESULT: READY"
    fi
    exit 0
fi
