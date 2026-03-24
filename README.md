# madelin

`madelin` is a monorepo for a bridge-guided Linux kernel fuzzing workflow:

1. `uafx/` performs static cross-entry UAF analysis.
2. `uaf-bridge/` converts static warnings into canonical seed artifacts.
3. `mock/` imports those seeds and runs Healer-based seeded fuzzing.

The current practical target is seeded arm64 KVM fuzzing.

## Current Verifier Scope

The verifier stack is intentionally narrow today:

- **Verdict layer**: current crash matching is KASAN/text-log driven and focused on candidate `loc0`/`loc1`, subsystem frames, and simple execution metadata.
- **Runnable witness layer**: currently supports the narrow arm64 KVM subset `openat$KVM`, `KVM_CREATE_VM`, `KVM_CREATE_VCPU`, `KVM_ARM_VCPU_INIT`, `KVM_SET_ONE_REG`, `KVM_GET_ONE_REG`, and `KVM_RUN`.
- **Harness layer**: currently supports one micro-harness family only, the arm64 KVM timer close-vs-run candidate shape (`kvm_timer_vcpu_terminate` vs `kvm_timer_should_fire` through `kvm_vcpu_ioctl`).
- **Unsupported cases**: broader KVM device/IRQ templates, non-KVM candidates, broad subsystem expansion, and generalized semantic argument synthesis are still out of scope.

## Repository Layout

- `uafx/`
  Static producer of cross-entry UAF candidates.
- `uaf-bridge/`
  Canonical translator and witness generator:
  `UAFX export -> candidate.json -> witness_plan.json -> mock_seed.json`
- `mock/`
  Dynamic consumer:
  imports bridge seeds, prepares seeded corpus/relations/bias, validates startup assets, and launches seeded fuzzing.

## What Works Today

The startup path is hardened for the practical seeded workflow:

1. generate bridge seed
2. prepare MOCK seed workdir
3. validate prerequisites
4. do a dry-run first
5. launch a short seeded fuzzing run

The intended operator flow is:

```bash
uafx -> uaf-bridge -> mock
```

## Quick Start

### 1. Set up `uaf-bridge`

```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/uaf-bridge
python3 -m venv .venv_ci
source .venv_ci/bin/activate
pip install -e .[dev]
python scripts/check_env.py
```

### 2. Build `mock`

```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock
cargo build --release
```

If the build fails while preparing syzkaller, install these tools first:

```bash
wget   # or curl
sha384sum unzip patch make go
```

The patched syzkaller tree is expected at:

```bash
mock/target/release/syz-bin
```

If you are building on macOS and the release build does not produce `linux_arm64/syz-executor`, that is an environment limitation, not a silent success. For the arm64 KVM path you must either:

- build the syzkaller tree on a Linux host, then point `SYZ_DIR` at that tree
- or run the full arm64 KVM validation path on a Linux host directly

### 3. Generate bridge artifacts

```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/uaf-bridge
bash scripts/run_end_to_end_kvm_demo.sh
```

This should produce:

- `out/uafx_kvm_candidate.json`
- `out/uafx_kvm_plan.json`
- `out/uafx_kvm_mock_seed.json`
- `out/uafx_kvm_proof/summary.json`

### 4. Prepare seeded MOCK inputs

```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock
bash scripts/prepare_kvm_seed.sh
```

This should produce:

- `seed_workdir/input/*.prog`
- `seed_workdir/relations/bridge_seed.relations`
- `seed_workdir/bias.json`

### 5. Check startup prerequisites

Set `SYZ_DIR` to the patched syzkaller tree:

```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock
export SYZ_DIR="$PWD/target/release/syz-bin"
```

Then validate the runtime assets:

```bash
bash scripts/check_kvm_fuzz_prereqs.sh <arm64_disk_image> <ssh_key> <arm64_kernel_image>
```

The checker validates:

- disk image path
- SSH key path
- kernel image path
- seed input directory
- seed relations file
- bridge bias file
- syzkaller layout
- expected arm64 `syz-executor`

It also reports whether the optional Django model manager is reachable.

### 5b. Check witness / harness target prerequisites

Witness and harness modes execute against a Linux target over SSH. Before trying those modes, run:

```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock
export SYZ_DIR="$PWD/target/release/syz-bin"
bash scripts/check_remote_target.sh \
  --mode both \
  --target-host <host> \
  --ssh-key <ssh_key>
```

The checker verifies:

- SSH connectivity
- writable remote temp space
- readable `dmesg` or a clear failure reason
- remote `gcc` for harness mode
- local `syz-executor` / `syz-execprog` availability for witness mode

Current witness mode uploads `syz-executor` and `syz-execprog` from local `--syz-dir`; the target does not need those tools preinstalled on its PATH.

### 6. Do a dry-run first

```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock
export SYZ_DIR="$PWD/target/release/syz-bin"
bash scripts/run_kvm_seed_fuzz.sh --dry-run <arm64_disk_image> <ssh_key> <arm64_kernel_image>
```

This validates the full seeded configuration and writes:

```bash
output-kvm-seeded/debug-summary.json
```

### 7. Start a short seeded fuzzing run

```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock
export SYZ_DIR="$PWD/target/release/syz-bin"
bash scripts/run_kvm_seed_fuzz.sh --max-seconds 600 <arm64_disk_image> <ssh_key> <arm64_kernel_image>
```

## Narrow Smoke Foundations

Two conservative golden-path smoke scripts are available under the repo-root `scripts/` directory:

```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin
bash scripts/e2e_witness_smoke.sh
bash scripts/e2e_harness_smoke.sh
```

They always do local artifact generation first. If a real target or required runtime assets are missing, they stop after preflight or artifact generation with an explicit note instead of trying to guess around the environment.

## Runtime Assets You Must Provide

This repository does not bundle the real arm64 runtime images. You still need:

- an arm64 disk image
- the SSH private key for that image
- an arm64 kernel image

Without those assets, the dry-run and prereq checker can validate paths and configuration, but real fuzzing cannot start.

## Bridge Python Selection

The bridge-side scripts now choose the first interpreter that actually passes `uaf-bridge/scripts/check_env.py`, in this order:

1. `uaf-bridge/.venv_ci/bin/python`
2. `uaf-bridge/.venv/bin/python`
3. `uaf-bridge/.venv_sys/bin/python`
4. `python3`

If you want to pin a specific interpreter for the bridge demo or smoke scripts, export `PYTHON=/absolute/path/to/python` before running them.

## Optional Model Manager

The Django model manager is optional for:

- bridge seed generation
- seed preparation
- prerequisite checking
- seeded dry-run
- short seeded startup

If you want it running for longer fuzzing sessions:

```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock/tools/model_manager
python3 manage.py runserver
```

## Testing

### `uaf-bridge`

```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/uaf-bridge
.venv_ci/bin/python -m pytest
```

### `mock`

```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock
bash -n scripts/prepare_kvm_seed.sh
bash -n scripts/check_kvm_fuzz_prereqs.sh
bash -n scripts/run_kvm_seed_fuzz.sh
bash -n scripts/run_kvm_seeded_fuzz.sh
bash -n scripts/run_seeded_vs_unseeded_compare.sh

PYTHONPATH=. python3 -m unittest \
  tests/test_startup_workflow.py \
  tests/test_bridge_seed_import.py \
  tests/test_corpus_histogram.py \
  tests/test_corpus_prefix_metrics.py
```

Optional dry-run validation:

```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock
RUN_CARGO_DRY_RUN_TEST=1 PYTHONPATH=. python3 -m unittest tests/test_dry_run_summary.py
```

## More Detail

For subsystem-specific operational detail:

- `uaf-bridge/README.md`
- `mock/README.md`
- `PRD.md`
- `context.md`
- `docs/plans/docs/plans/v2-verifier-architecture.md`

`docs/plans/v2-verifier-architecture.md` now exists as a compatibility pointer because some handoffs still refer to the shorter path, but the nested `docs/plans/docs/plans/...` copy is the current canonical plan location in this workspace.
