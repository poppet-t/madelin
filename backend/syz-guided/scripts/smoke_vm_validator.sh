#!/usr/bin/env bash
# Smoke test for vm_validator.
#
# This smoke has two modes:
#   1. PREFLIGHT-ONLY (default): validates command construction, preflight logic,
#      and module imports without needing a real VM image.
#   2. FULL BOOT (if VM_KERNEL, VM_DISK, VM_SSH_KEY are set): attempts a real
#      QEMU TCG boot and one-shot execution.
#
# Exit on any failure.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
FIXTURES="$BACKEND_DIR/tests/fixtures"
OUT_DIR=$(mktemp -d)

echo "=== smoke_vm_validator ==="
echo "Output:   $OUT_DIR"

# ── Step 1: verify module imports ──
python3 -c "
import sys, pathlib
sys.path.insert(0, '$BACKEND_DIR')
from vm_validator.preflight import run_preflight, check_qemu, check_file
from vm_validator.vm_runner import build_qemu_cmd, wait_for_ssh
from vm_validator.prog_injector import build_inject_cmd, build_scp_cmd
from vm_validator.log_collector import extract_kasan, save_logs
from vm_validator.run_one import run_one
print('  [PASS] all vm_validator modules import successfully')
"

# ── Step 2: test QEMU command construction ──
python3 -c "
import sys, pathlib
sys.path.insert(0, '$BACKEND_DIR')
from vm_validator.vm_runner import build_qemu_cmd
cmd = build_qemu_cmd(
    kernel=pathlib.Path('/tmp/Image'),
    disk_image=pathlib.Path('/tmp/disk.qcow2'),
    ssh_port=10022,
)
assert 'qemu-system-aarch64' in cmd[0], f'unexpected cmd[0]: {cmd[0]}'
assert '-accel' in cmd, 'missing -accel'
assert 'tcg' in cmd, 'missing tcg'
assert '-nographic' in cmd, 'missing -nographic'
assert '-no-reboot' in cmd, 'missing -no-reboot'
# Check SSH port forwarding is present.
joined = ' '.join(cmd)
assert '10022' in joined, 'missing SSH port forward'
print('  [PASS] QEMU command construction correct')
"

# ── Step 3: test KASAN extraction ──
python3 -c "
import sys
sys.path.insert(0, '$BACKEND_DIR')
from vm_validator.log_collector import extract_kasan

# Positive case: KASAN present.
dmesg_with_kasan = '''
[   12.345] some normal log
[   13.456] BUG: KASAN: use-after-free in kvm_timer_update+0x1c/0x40
[   13.457] Read of size 8 at addr ffff0000deadbeef
[   13.458] Call Trace:
[   13.459]  kvm_timer_update+0x1c/0x40
[   13.460]  kvm_arch_vcpu_ioctl_run+0x2bc/0x8e0
[   13.461] ====================================
[   13.462] more stuff
'''
result = extract_kasan(dmesg_with_kasan)
assert result is not None, 'should have found KASAN'
assert 'BUG: KASAN' in result, 'missing KASAN header'

# Negative case: no KASAN.
result2 = extract_kasan('just normal kernel log\nnothing here\n')
assert result2 is None, 'should not have found KASAN'

# Empty case.
result3 = extract_kasan('')
assert result3 is None, 'empty string should return None'

print('  [PASS] KASAN extraction logic correct')
"

# ── Step 4: test preflight with missing files ──
python3 -c "
import sys, pathlib
sys.path.insert(0, '$BACKEND_DIR')
from vm_validator.preflight import run_preflight

result = run_preflight(
    kernel=pathlib.Path('/nonexistent/Image'),
    disk_image=pathlib.Path('/nonexistent/disk.qcow2'),
    ssh_key=pathlib.Path('/nonexistent/id_rsa'),
)
assert not result['ready'], 'preflight should fail with missing files'
assert result['failed_count'] >= 3, f'expected >= 3 failures, got {result[\"failed_count\"]}'
print('  [PASS] preflight correctly rejects missing files')
"

# ── Step 5: check if real VM assets exist ──
if [ -n "${VM_KERNEL:-}" ] && [ -n "${VM_DISK:-}" ] && [ -n "${VM_SSH_KEY:-}" ]; then
    echo ""
    echo "  VM assets detected — attempting full boot smoke..."

    PROG_FILE="$OUT_DIR/test_seed.prog"
    # Generate a seed from fixtures if available.
    if [ -f "$FIXTURES/candidate.json" ] && [ -f "$FIXTURES/witness_plan.json" ]; then
        python3 "$BACKEND_DIR/state_model/build_state_model.py" \
            --candidate "$FIXTURES/candidate.json" \
            --witness-plan "$FIXTURES/witness_plan.json" \
            --out-dir "$OUT_DIR"
        python3 "$BACKEND_DIR/seedgen/synthesize_seeds.py" \
            --state-model "$OUT_DIR/state_model_v1.json" \
            --out-dir "$OUT_DIR/seeds"
        PROG_FILE="$OUT_DIR/seeds/seed_full_run.prog"
    else
        # Minimal dummy prog.
        echo "# dummy prog for smoke" > "$PROG_FILE"
    fi

    python3 -m vm_validator.run_one \
        --kernel "$VM_KERNEL" \
        --disk-image "$VM_DISK" \
        --ssh-key "$VM_SSH_KEY" \
        --prog "$PROG_FILE" \
        --out-dir "$OUT_DIR/vm_run" \
        ${VM_SYZ_EXECPROG:+--syz-execprog "$VM_SYZ_EXECPROG"} \
        --ssh-port "${VM_SSH_PORT:-10022}"

    echo "  [PASS] full boot smoke completed"
    echo "  Results: $OUT_DIR/vm_run/vm_run_log.json"
    SMOKE_TYPE="full_boot"
else
    echo ""
    echo "  No VM assets (VM_KERNEL, VM_DISK, VM_SSH_KEY not set)."
    echo "  This is a PREFLIGHT-ONLY smoke."
    SMOKE_TYPE="preflight_only"
fi

echo ""
echo "=== smoke_vm_validator PASSED (${SMOKE_TYPE}) ==="
echo "Artifacts in: $OUT_DIR"
