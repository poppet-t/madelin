# madelin

`madelin` is a monorepo for an artifact-driven Linux kernel fuzzing workflow that turns
UAFX-discovered cross-entry UAF candidates into dynamic validation attempts:

1. `uafx/` performs static cross-entry UAF analysis.
2. `uaf-bridge/` converts static warnings into canonical artifacts (`candidate.json`, `witness_plan.json`).
3. `backend/syz-guided/` is the v1 syzkaller-based runtime backend: consumes bridge
   artifacts, synthesizes seeds, orchestrates campaigns, and triages crashes against
   the original candidate.

The current practical target is Linux arm64 KVM.

For AI/operator handoff, see [docs/ai/OPENCLAW-RUNBOOK.md](docs/ai/OPENCLAW-RUNBOOK.md).

## Current Verifier Scope

The verifier stack is intentionally narrow today:

- **Verdict layer**: current crash matching is KASAN/text-log driven and focused on
  candidate `loc0`/`loc1`, subsystem frames, and simple execution metadata.
- **Runnable witness layer**: currently supports the narrow arm64 KVM subset
  `openat$KVM`, `KVM_CREATE_VM`, `KVM_CREATE_VCPU`, `KVM_ARM_VCPU_INIT`,
  `KVM_SET_ONE_REG`, `KVM_GET_ONE_REG`, and `KVM_RUN`.
- **Harness layer**: currently supports one micro-harness family only, the arm64 KVM
  timer close-vs-run candidate shape (`kvm_timer_vcpu_terminate` vs
  `kvm_timer_should_fire` through `kvm_vcpu_ioctl`).
- **Unsupported cases**: broader KVM device/IRQ templates, non-KVM candidates, broad
  subsystem expansion, and generalized semantic argument synthesis are still out of scope.

## Repository Layout

- `uafx/`
  Static producer of cross-entry UAF candidates.
- `uaf-bridge/`
  Canonical translator and witness generator:
  `UAFX export → candidate.json → witness_plan.json`
- `backend/syz-guided/`
  v1 syzkaller-based runtime backend:
  `candidate.json + witness_plan.json → state model → seeds → orchestrated campaign → candidate-aware triage`
- `syzkaller/`
  Upstream syzkaller source tree (clean checkout — build locally to produce binaries).
- `syzkaller-runtime-export/`
  Preserved arm64 KVM runtime environment for reproducible execution
  (kernel image, disk image, SSH key, manager config).

## What Works Today

### v1 syzkaller backend (`backend/syz-guided/`)

- State model generation is deterministic for the KVM fixture candidate.
- Seed synthesis emits 4 prefix-preserving `.prog` seeds.
- Bounded orchestrator with scoring, hot/cold queuing, and campaign lifecycle.
- Candidate-aware triage emits structured `triage_report_v1.json` with verdict
  classification.
- Prefix-safe mutation preserves bootstrap prefix and sticky calls.
- Relation guard validates resource chain integrity post-mutation.
- 84 unit tests pass; 4 smoke scripts pass (seedgen, campaign, triage, vm_validator).

### macOS QEMU TCG validation (`vm_validator/`)

- One-shot execution proven on macOS under QEMU TCG (software emulation).
- Full pipeline exercised: seed → syz-execprog → syz-executor → syscalls → dmesg → triage.
- KVM ioctls return EINVAL under TCG (no `/dev/kvm`) — expected, not a code issue.
- Triage correctly produces `insufficient_data` verdict when no crash occurs.

### What remains

- Real KVM-backed candidate trigger (requires Linux arm64 KVM host).
- Bounded syz-manager campaign with coverage signal.
- Repro wrapper validation on real crash input.
- See `plans/linux-kvm-runbook.md` for the concrete execution plan.

The intended operator flow is:

```
uafx → uaf-bridge → backend/syz-guided
```

## Quick Start

### Backend smoke (no KVM target required)

```bash
cd /path/to/madelin/backend/syz-guided
bash scripts/smoke_seedgen.sh
bash scripts/smoke_campaign.sh
bash scripts/smoke_triage.sh
```

All three pass without a live kernel. These validate seed synthesis, the orchestrator
lifecycle, and triage report emission against the KVM fixture.

### Full arm64 KVM path

Follow steps 1–5 below.

### 1. Set up `uaf-bridge`

```bash
cd uaf-bridge
python3 -m venv .venv_ci
source .venv_ci/bin/activate
pip install -e .[dev]
python scripts/check_env.py
```

### 2. Build syzkaller

```bash
cd syzkaller
make TARGETOS=linux TARGETARCH=arm64
# Produces bin/linux_arm64/syz-manager, syz-executor, syz-execprog
export SYZ_DIR="$PWD/bin"
```

If you are building on macOS, the `linux_arm64` targets require a Linux cross-build
environment. For the arm64 KVM path either:
- build on a Linux host, then point `SYZ_DIR` at that tree's `bin/`, or
- run the full arm64 KVM validation path on a Linux host directly.

### 3. Generate bridge artifacts

```bash
cd uaf-bridge
bash scripts/run_end_to_end_kvm_demo.sh
```

This produces:
- `out/uafx_kvm_candidate.json`
- `out/uafx_kvm_plan.json`
- `out/uafx_kvm_proof/summary.json`

### 4. Run the backend smoke against bridge artifacts

```bash
cd backend/syz-guided
bash scripts/smoke_seedgen.sh
bash scripts/smoke_campaign.sh
bash scripts/smoke_triage.sh
```

### 5. Live validation (requires arm64 KVM environment)

**On macOS (TCG, no KVM)** — one-shot seed execution:
```bash
cd backend/syz-guided
bash scripts/smoke_vm_validator.sh
```

**On Linux KVM host** — check host readiness, then one-shot or full campaign:
```bash
# Preflight
bash backend/syz-guided/scripts/check_linux_kvm_host.sh \
  --kernel syzkaller-runtime-export/Image \
  --disk syzkaller-runtime-export/arm64-standalone.qcow2 \
  --ssh-key syzkaller-runtime-export/id_rsa

# One-shot seed execution
bash backend/syz-guided/scripts/run_linux_kvm_one_shot.sh \
  --kernel syzkaller-runtime-export/Image \
  --disk syzkaller-runtime-export/arm64-standalone.qcow2 \
  --ssh-key syzkaller-runtime-export/id_rsa \
  --syz-execprog syzkaller/bin/linux_arm64/syz-execprog \
  --syz-executor syzkaller/bin/linux_arm64/syz-executor \
  --prog backend/syz-guided/tests/fixtures/generated/seeds/seed_full_run.prog \
  --out-dir /tmp/kvm_run

# Bounded syz-manager campaign
bash backend/syz-guided/scripts/run_linux_syz_manager.sh \
  --config /tmp/kvm_run/syz-manager.cfg \
  --out-dir /tmp/kvm_campaign \
  --timeout 600
```

See `plans/linux-kvm-runbook.md` for the full step-by-step guide.

## Runtime Assets

This repository bundles a preserved arm64 KVM runtime environment in
`syzkaller-runtime-export/`:

- `arm64-kvm-isolated.cfg` — syz-manager config used in the known working run
- `Image` — arm64 kernel image (148 MB, `7.0.0-rc5-gbbeb83d3182a`)
- `arm64-standalone.qcow2` — bootable root disk image (11.5 GiB virtual, ext4, fixed fstab)
- `arm64-isolated-overlay.qcow2` — legacy overlay (69 MB, requires missing base — do not use)
- `id_rsa` / `id_rsa.pub` — SSH keypair
- `SHA256SUMS.txt` — checksums for integrity verification

The environment targets an isolated QEMU/KVM mode with `syz-manager` attaching to a
pre-booted VM at `root@127.0.0.1:10022`. The `arm64-standalone.qcow2` is the
canonical bootable image; the overlay is kept only as a historical reference.

## Bridge Python Selection

The bridge-side scripts choose the first interpreter that passes
`uaf-bridge/scripts/check_env.py`, in this order:

1. `uaf-bridge/.venv_ci/bin/python`
2. `uaf-bridge/.venv/bin/python`
3. `uaf-bridge/.venv_sys/bin/python`
4. `python3`

Export `PYTHON=/absolute/path/to/python` to pin a specific interpreter.

## Testing

### `backend/syz-guided`

```bash
cd /path/to/madelin
python3 backend/syz-guided/tests/test_state_model.py -v
python3 backend/syz-guided/tests/test_seedgen.py -v
python3 backend/syz-guided/tests/test_score.py -v
python3 backend/syz-guided/tests/test_triage.py -v
python3 backend/syz-guided/tests/test_relation_guard.py -v
python3 backend/syz-guided/tests/test_vm_validator.py -v
```

Smoke scripts (no KVM target required):

```bash
cd backend/syz-guided
bash scripts/smoke_seedgen.sh
bash scripts/smoke_campaign.sh
bash scripts/smoke_triage.sh
```

### `uaf-bridge`

```bash
cd uaf-bridge
.venv_ci/bin/python -m pytest
```

## More Detail

- `context/overview.md` — project purpose and v1 scope
- `context/architecture.md` — pipeline stages and backend design principles
- `context/current-status.md` — what is runnable today and what remains
- `uaf-bridge/README.md` — bridge stage detail
- `plans/current.md` — active implementation plan
- `plans/validation-report.md` — recorded validation evidence
- `plans/syzkaller-runtime-proof.md` — proof of which syzkaller path is used
- `plans/mock-removal-audit.md` — MOCK reference audit and cleanup record
- `plans/linux-kvm-runbook.md` — concrete Linux KVM host execution guide
