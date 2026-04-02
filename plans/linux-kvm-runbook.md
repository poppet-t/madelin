# Linux KVM host runbook

## Purpose

Execute the already-validated backend + vm_validator flow on a real Linux KVM host
to obtain KVM-backed ioctl behavior, KASAN crash evidence, and coverage signals.

This is the single remaining blocker for full v1 validation (see `plans/current.md`).

## Proven baseline (macOS TCG)

The following is already validated under QEMU TCG on macOS:

- Full artifact flow: candidate → state_model → seeds → VM execution → dmesg → triage
- syz-execprog parses text `.prog` seeds directly
- syz-executor connects via flatrpc, executes syscalls
- Triage produces correct `insufficient_data` verdict when no crash occurs
- KVM ioctls return EINVAL under TCG (no `/dev/kvm`) — expected

What TCG cannot provide:
- `/dev/kvm` device in guest
- Real KVM kernel codepath execution
- KASAN UAF crash triggers
- Coverage signal from KCOV

---

## 1. Host prerequisites

### Hardware / OS

| Requirement | Check command |
|---|---|
| Linux kernel with KVM | `uname -r` (5.x+ recommended) |
| arm64 architecture | `uname -m` → `aarch64` |
| KVM module loaded | `lsmod \| grep kvm` |
| `/dev/kvm` accessible | `ls -la /dev/kvm` |
| KVM usable by current user | `test -w /dev/kvm && echo ok` |

If the host is x86_64 with nested arm64 virt, ensure the nested hypervisor
exposes `/dev/kvm` to the arm64 guest.

### Software

| Tool | Version | Check |
|---|---|---|
| QEMU (qemu-system-aarch64) | 7.0+ | `qemu-system-aarch64 --version` |
| Python 3.10+ | — | `python3 --version` |
| Go 1.21+ | — | `go version` |
| GCC cross-compiler (optional) | aarch64-linux-gnu-gcc | `which aarch64-linux-gnu-gcc` |
| SSH client | — | `which ssh` |

If host is native aarch64, no cross-compiler is needed — build natively.

### Disk space

- ~15 GiB for disk image + kernel + syzkaller build + workdir
- Additional ~5 GiB for syz-manager workdir during campaign

---

## 2. Required runtime assets

All paths are relative to the repo root.

### From repo

| Asset | Repo path | Notes |
|---|---|---|
| Kernel Image | `syzkaller-runtime-export/Image` | 141M, arm64 `7.0.0-rc5-gbbeb83d3182a` |
| Guest disk | `syzkaller-runtime-export/arm64-standalone.qcow2` | 11.5 GiB virtual, ext4, fixed fstab |
| SSH key | `syzkaller-runtime-export/id_rsa` | Matches authorized_keys in guest |
| SSH pubkey | `syzkaller-runtime-export/id_rsa.pub` | — |
| Candidate | `backend/syz-guided/tests/fixtures/candidate.json` | KVM UAF candidate |
| Witness plan | `backend/syz-guided/tests/fixtures/witness_plan.json` | — |
| Generated state model | `backend/syz-guided/tests/fixtures/generated/state_model_v1.json` | — |
| Generated target profile | `backend/syz-guided/tests/fixtures/generated/target_profile.json` | — |
| Generated relation graph | `backend/syz-guided/tests/fixtures/generated/relation_graph_v1.json` | — |
| Seeds | `backend/syz-guided/tests/fixtures/generated/seeds/seed_*.prog` | 4 seeds |
| Isolated mode config | `syzkaller-runtime-export/arm64-kvm-isolated.cfg` | Reference — paths need updating |

### Kernel considerations

The bundled Image (`7.0.0-rc5-gbbeb83d3182a`) was built with:
- `CONFIG_KVM=y`
- `CONFIG_KASAN=y` (assumed — required for KASAN crash detection)
- `CONFIG_KCOV=y` (assumed — required for coverage)

If these are not present, a custom kernel build is required. Verify inside guest:
```bash
zcat /proc/config.gz | grep -E 'CONFIG_KVM|CONFIG_KASAN|CONFIG_KCOV'
```

---

## 3. Syzkaller build

### Build from in-repo source

The repo contains a clean upstream syzkaller checkout at `syzkaller/`.

```bash
cd syzkaller/

# Native build on arm64 Linux host:
make TARGETOS=linux TARGETARCH=arm64

# Cross-build on x86_64 Linux host:
make TARGETOS=linux TARGETARCH=arm64 HOSTOS=linux HOSTARCH=amd64
```

### Expected binaries

After build, `SYZ_DIR` should point to the `syzkaller/` directory.

| Binary | Path under SYZ_DIR | Role |
|---|---|---|
| syz-manager | `bin/syz-manager` | Campaign manager (runs on host) |
| syz-execprog | `bin/linux_arm64/syz-execprog` | Program executor (runs in guest) |
| syz-executor | `bin/linux_arm64/syz-executor` | Syscall executor (runs in guest) |

### Verify build

```bash
file bin/syz-manager           # ELF 64-bit LSB executable, ARM aarch64 (or host arch)
file bin/linux_arm64/syz-execprog  # ELF 64-bit LSB executable, ARM aarch64
file bin/linux_arm64/syz-executor  # ELF 64-bit LSB executable, ARM aarch64

# Confirm syz-executor was built (requires CGO):
ls -la bin/linux_arm64/syz-executor
```

**syz-executor CGO note**: On macOS TCG, syz-executor was compiled inside the guest
because no Linux cross-toolchain was available. On a native arm64 Linux host, `make`
builds syz-executor natively via CGO. On an x86_64 host, ensure
`aarch64-linux-gnu-gcc` is installed for CGO cross-compilation.

---

## 4. Backend artifact regeneration

Regenerate all runtime artifacts from the fixture candidate. Run from repo root.

### State model + target profile + relation graph

```bash
cd backend/syz-guided/

python3 state_model/build_state_model.py \
    --candidate tests/fixtures/candidate.json \
    --witness   tests/fixtures/witness_plan.json \
    --out-dir   /tmp/kvm_run/artifacts/
```

**Outputs**:
- `/tmp/kvm_run/artifacts/state_model_v1.json`
- `/tmp/kvm_run/artifacts/target_profile.json`
- `/tmp/kvm_run/artifacts/relation_graph_v1.json`

### Seeds

```bash
python3 seedgen/synthesize_seeds.py \
    --candidate tests/fixtures/candidate.json \
    --witness   tests/fixtures/witness_plan.json \
    --out-dir   /tmp/kvm_run/seeds/
```

**Outputs**: 4 `.prog` files + `seed_manifest.json` in `/tmp/kvm_run/seeds/`.

### Verify artifacts

```bash
python3 state_model/validate_state_model.py /tmp/kvm_run/artifacts/state_model_v1.json
# Expected: "state_model_v1.json validates against schema."
```

Or use the existing smoke scripts:
```bash
bash scripts/smoke_seedgen.sh
```

---

## 5. One-shot validation (before syz-manager)

This mirrors the macOS TCG validation but with real KVM. Run this first to confirm
the environment works before attempting a full syz-manager campaign.

### 5a. Boot guest under QEMU/KVM

Key difference from macOS: `-accel kvm` instead of `-accel tcg`.

```bash
RUNTIME=syzkaller-runtime-export

qemu-system-aarch64 \
    -machine virt \
    -accel kvm \
    -cpu host \
    -m 2048 \
    -nographic \
    -kernel ${RUNTIME}/Image \
    -drive if=virtio,format=qcow2,file=${RUNTIME}/arm64-standalone.qcow2 \
    -append "root=/dev/vda1 console=ttyAMA0 kasan.fault=panic" \
    -netdev user,id=net0,hostfwd=tcp:127.0.0.1:10022-:22 \
    -device virtio-net-pci,netdev=net0 \
    -no-reboot &

QEMU_PID=$!
```

### 5b. Wait for SSH and verify KVM inside guest

```bash
# Wait for SSH (should be much faster than TCG — seconds, not minutes)
while ! ssh -o StrictHostKeyChecking=no -o ConnectTimeout=2 \
    -i ${RUNTIME}/id_rsa -p 10022 root@127.0.0.1 true 2>/dev/null; do
    sleep 2
done

# Verify /dev/kvm
ssh -i ${RUNTIME}/id_rsa -p 10022 root@127.0.0.1 \
    'ls -la /dev/kvm && echo "KVM: available" || echo "KVM: MISSING"'
```

If `/dev/kvm` is missing inside the guest, the kernel Image may lack `CONFIG_KVM=y`
or the host is not passing through KVM properly. Stop here and resolve.

### 5c. Copy binaries and seed into guest

```bash
SYZ_DIR=syzkaller/

scp -i ${RUNTIME}/id_rsa -P 10022 \
    ${SYZ_DIR}/bin/linux_arm64/syz-execprog \
    ${SYZ_DIR}/bin/linux_arm64/syz-executor \
    root@127.0.0.1:/root/

scp -i ${RUNTIME}/id_rsa -P 10022 \
    /tmp/kvm_run/seeds/seed_full_run.prog \
    root@127.0.0.1:/root/
```

### 5d. Run one seed

```bash
ssh -i ${RUNTIME}/id_rsa -p 10022 root@127.0.0.1 \
    'cd /root && chmod +x syz-execprog syz-executor && \
     ./syz-execprog -executor=./syz-executor -repeat=0 -procs=1 -slowdown=1 seed_full_run.prog 2>&1' \
    | tee /tmp/kvm_run/execprog_output.txt
```

Note: `-slowdown=1` (default) is correct for KVM. TCG required `-slowdown=10`.

### 5e. Collect dmesg

```bash
ssh -i ${RUNTIME}/id_rsa -p 10022 root@127.0.0.1 dmesg \
    > /tmp/kvm_run/guest_dmesg.txt

# Check for KASAN reports:
grep -c "BUG: KASAN" /tmp/kvm_run/guest_dmesg.txt
```

### 5f. Run candidate-aware triage

```bash
cd backend/syz-guided/

python3 -c "
import json, sys
sys.path.insert(0, '.')
from triage.report import build_triage_report

with open('/tmp/kvm_run/guest_dmesg.txt') as f:
    crash_text = f.read()
with open('/tmp/kvm_run/artifacts/target_profile.json') as f:
    tp = json.load(f)
with open('/tmp/kvm_run/artifacts/state_model_v1.json') as f:
    sm = json.load(f)

report = build_triage_report(crash_text, tp, sm)
with open('/tmp/kvm_run/triage_report_v1.json', 'w') as f:
    json.dump(report, f, indent=2)
print(f'Verdict: {report[\"verdict\"]}')
print(f'Match score: {report[\"candidate_match\"][\"match_score\"]}')
"
```

### 5g. Use vm_validator module (alternative)

The existing `vm_validator/run_one.py` can also be used, but it hardcodes
`-accel tcg`. For KVM, either:
1. Modify `vm_runner.py` to accept an `accel` parameter (future Phase B work), or
2. Run the manual steps above.

```bash
# If vm_runner.py is updated to support -accel kvm:
cd backend/syz-guided/
python3 -m vm_validator.run_one \
    --kernel ../../syzkaller-runtime-export/Image \
    --disk-image ../../syzkaller-runtime-export/arm64-standalone.qcow2 \
    --ssh-key ../../syzkaller-runtime-export/id_rsa \
    --prog /tmp/kvm_run/seeds/seed_full_run.prog \
    --syz-execprog ../../syzkaller/bin/linux_arm64/syz-execprog \
    --executor-path /root/syz-executor \
    --state-model /tmp/kvm_run/artifacts/state_model_v1.json \
    --target-profile /tmp/kvm_run/artifacts/target_profile.json \
    --out-dir /tmp/kvm_run/output/
```

### 5h. Expected outcomes

| Scenario | Verdict | Match score | What it means |
|---|---|---|---|
| No KASAN, KVM ioctls succeed | `insufficient_data` | 0.0 | KVM codepaths exercised but no UAF triggered |
| KASAN UAF in KVM focus frames | `confirmed` or `plausible` | > 0.5 | Candidate validated |
| KASAN crash outside focus frames | `unrelated` | < 0.3 | Real crash but not the target candidate |

### 5i. Shutdown

```bash
ssh -i ${RUNTIME}/id_rsa -p 10022 root@127.0.0.1 poweroff
wait $QEMU_PID
```

---

## 6. Bounded syz-manager campaign

Only attempt this after the one-shot validation in section 5 succeeds.

### 6a. Generate syz-manager config

Two options:

**Option A — use backend config generator** (recommended):

```bash
cd backend/syz-guided/

python3 -c "
import json, pathlib, sys
sys.path.insert(0, '.')
from integration.syzkaller_runner import generate_syz_config, write_syz_config

with open('/tmp/kvm_run/artifacts/state_model_v1.json') as f:
    sm = json.load(f)

config = generate_syz_config(
    state_model=sm,
    seeds_dir=pathlib.Path('/tmp/kvm_run/seeds'),
    work_dir=pathlib.Path('/tmp/kvm_run'),
    kernel_image=pathlib.Path('../../syzkaller-runtime-export/Image'),
    disk_image=pathlib.Path('../../syzkaller-runtime-export/arm64-standalone.qcow2'),
    ssh_key=pathlib.Path('../../syzkaller-runtime-export/id_rsa'),
    syz_dir=pathlib.Path('../../syzkaller'),
    max_duration_seconds=600,
)
write_syz_config(config, pathlib.Path('/tmp/kvm_run/syz-manager.cfg'))
print(json.dumps(config, indent=2))
"
```

**Note**: `generate_syz_config()` produces a `type: qemu` config. For the existing
runtime-export environment (pre-booted VM), use `type: isolated` instead. See
option B.

**Option B — adapt the existing isolated config**:

Copy and update `syzkaller-runtime-export/arm64-kvm-isolated.cfg`:

```bash
cp syzkaller-runtime-export/arm64-kvm-isolated.cfg /tmp/kvm_run/syz-manager-isolated.cfg
```

Update paths in the copy:
- `"syzkaller"` → absolute path to `syzkaller/` in repo
- `"kernel_obj"` → directory containing the kernel Image
- `"kernel_src"` → same (or path to kernel source if available)
- `"sshkey"` → absolute path to `syzkaller-runtime-export/id_rsa`
- `"workdir"` → `/tmp/kvm_run/syz-workdir`
- `"vm.targets"` → `["127.0.0.1:10022"]` (matches SSH port forward)
- `"vm.target_dir"` → `/root/syzkaller` (guest-side directory for binaries)

The `enable_syscalls` list is already correct for KVM candidates.

### 6b. Run syz-manager

**For isolated mode** (pre-booted VM from section 5):

```bash
# Ensure the VM from section 5 is still running.
# Create target_dir on guest:
ssh -i syzkaller-runtime-export/id_rsa -p 10022 root@127.0.0.1 \
    'mkdir -p /root/syzkaller'

# Launch syz-manager:
syzkaller/bin/syz-manager -config /tmp/kvm_run/syz-manager-isolated.cfg
```

**For QEMU mode** (syz-manager manages VM lifecycle):

```bash
syzkaller/bin/syz-manager -config /tmp/kvm_run/syz-manager.cfg
```

### 6c. Success criteria

| Criterion | Evidence |
|---|---|
| Manager starts | HTTP dashboard accessible at configured port |
| VM connects | Manager log shows "machine connected" or equivalent |
| Programs execute | Non-zero `exec total` in dashboard |
| Coverage signal | Non-zero `cover` in dashboard |
| Seeds injected | Corpus contains seed-derived programs |
| Campaign completes | Manager exits after `max_duration_seconds` or manual stop |
| Crash artifacts | `workdir/crashes/` contains crash logs (if crashes occur) |

### 6d. Collect campaign artifacts

After syz-manager stops:

```bash
# Campaign corpus
ls /tmp/kvm_run/syz-workdir/corpus/

# Crash logs (if any)
ls /tmp/kvm_run/syz-workdir/crashes/

# Copy any crash reports for triage
for crash in /tmp/kvm_run/syz-workdir/crashes/*/log*; do
    cp "$crash" /tmp/kvm_run/crash_logs/
done
```

### 6e. Triage campaign crashes

For each crash log:

```bash
cd backend/syz-guided/
python3 -c "
import json, sys
sys.path.insert(0, '.')
from triage.report import build_triage_report

with open('/tmp/kvm_run/crash_logs/log0') as f:
    crash_text = f.read()
with open('/tmp/kvm_run/artifacts/target_profile.json') as f:
    tp = json.load(f)
with open('/tmp/kvm_run/artifacts/state_model_v1.json') as f:
    sm = json.load(f)

report = build_triage_report(crash_text, tp, sm)
print(f'Verdict: {report[\"verdict\"]}')
print(f'Match score: {report[\"candidate_match\"][\"match_score\"]}')
with open('/tmp/kvm_run/triage_campaign_report.json', 'w') as f:
    json.dump(report, f, indent=2)
"
```

---

## 7. Evidence to record

After each execution phase, record results in `plans/validation-report.md`.

### One-shot evidence

| Item | Record |
|---|---|
| Host info | `uname -a`, `/dev/kvm` status |
| Guest `/dev/kvm` | Present/absent, permissions |
| syz-execprog output | Exact command, exit code, first/last 20 lines |
| KVM ioctl results | Success/EINVAL/other (from execprog output) |
| dmesg excerpt | KASAN section or "no KASAN detected" |
| Triage verdict | `verdict` field from `triage_report_v1.json` |
| Triage match score | `candidate_match.match_score` |

### Campaign evidence

| Item | Record |
|---|---|
| syz-manager config used | Full config (redact paths if needed) |
| Duration | Actual runtime in seconds |
| Programs executed | `exec total` from dashboard |
| Coverage | `cover` from dashboard |
| Crashes found | Count, types |
| Crash triage verdicts | Per-crash verdict + match_score |

### Verdict categories

| Verdict | Meaning | Next step |
|---|---|---|
| `confirmed` | KASAN UAF matches candidate focus frames | Document as v1 success |
| `plausible` | Crash plausibly related but not exact match | Investigate with repro wrapper |
| `unrelated` | Real crash but outside candidate scope | Record, do not claim as candidate hit |
| `insufficient_data` | No crash or insufficient signal | Increase campaign duration or check kernel config |

---

## 8. macOS TCG vs Linux KVM split

### Reusable across both environments

| Component | Path |
|---|---|
| State model builder | `backend/syz-guided/state_model/build_state_model.py` |
| Seed synthesizer | `backend/syz-guided/seedgen/synthesize_seeds.py` |
| Triage pipeline | `backend/syz-guided/triage/report.py` |
| Schema validation | `backend/syz-guided/state_model/validate_state_model.py` |
| Orchestrator logic | `backend/syz-guided/orchestrator/campaign.py` |
| All unit tests | `backend/syz-guided/tests/test_*.py` |

### Linux-KVM-specific steps

| Step | Why Linux-only |
|---|---|
| QEMU `-accel kvm` | Requires `/dev/kvm` on host |
| syz-executor native build | Requires Linux CGO or native aarch64 gcc |
| syz-manager campaign | Requires live KVM for meaningful execution |
| Coverage collection | Requires KCOV in guest kernel |
| Real KASAN crash triage | Requires KVM codepaths to be exercised |

### Still blocked until a real Linux KVM host is available

- Confirming the bundled kernel has `CONFIG_KASAN=y` and `CONFIG_KCOV=y`
- Observing real KVM ioctl success (vs EINVAL under TCG)
- Triggering KASAN UAF in KVM subsystem
- Running a bounded syz-manager campaign with coverage
- Producing a non-`insufficient_data` triage verdict
- Validating the repro wrapper (`backend/syz-guided/repro/candidate_repro.py`) on real crash input

### vm_runner.py adaptation needed (Phase B)

The current `vm_runner.py` hardcodes `-accel tcg`. For Linux KVM, it needs:
- Accept an `accel` parameter (`tcg` or `kvm`)
- Use `-cpu host` instead of `-cpu cortex-a57` when accel is `kvm`
- Reduce boot timeout (KVM boots in seconds, not minutes)
- Keep `-slowdown=1` as default for KVM

This is a small code change (~10 lines) but belongs in implementation Phase B,
not this planning phase.

---

## Appendix: reference config (isolated mode)

Adapted from `syzkaller-runtime-export/arm64-kvm-isolated.cfg` with placeholder paths:

```json
{
  "name": "arm64-kvm-isolated",
  "target": "linux/arm64",
  "http": "127.0.0.1:56742",
  "rpc": "127.0.0.1:0",
  "workdir": "/tmp/kvm_run/syz-workdir",
  "syzkaller": "/absolute/path/to/madelin/syzkaller",
  "kernel_obj": "/absolute/path/to/madelin/syzkaller-runtime-export",
  "kernel_src": "/absolute/path/to/madelin/syzkaller-runtime-export",
  "sshkey": "/absolute/path/to/madelin/syzkaller-runtime-export/id_rsa",
  "ssh_user": "root",
  "sandbox": "none",
  "procs": 2,
  "cover": true,
  "reproduce": false,
  "type": "isolated",
  "enable_syscalls": [
    "openat$kvm",
    "ioctl$KVM_CREATE_VM",
    "ioctl$KVM_CREATE_VCPU",
    "ioctl$KVM_ARM_VCPU_INIT",
    "ioctl$KVM_RUN",
    "ioctl$KVM_SET_ONE_REG",
    "ioctl$KVM_GET_ONE_REG",
    "ioctl$KVM_CREATE_DEVICE",
    "ioctl$KVM_SET_DEVICE_ATTR",
    "ioctl$KVM_GET_DEVICE_ATTR",
    "ioctl$KVM_HAS_DEVICE_ATTR",
    "ioctl$KVM_IRQ_LINE",
    "ioctl$KVM_SET_USER_MEMORY_REGION",
    "mmap"
  ],
  "vm": {
    "targets": ["127.0.0.1:10022"],
    "target_dir": "/root/syzkaller",
    "target_reboot": false
  }
}
```
