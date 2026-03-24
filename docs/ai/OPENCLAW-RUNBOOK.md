# OpenClaw Runbook

## Purpose
Use this document when OpenClaw is operating `madelin` on a Linux-capable VPS.

OpenClaw should use this runbook to:
- understand the repo structure and subsystem ownership
- run the supported arm64 KVM workflow in the correct order
- avoid false claims about support or validation
- maintain the repo without drifting artifact contracts

## Monorepo Structure

### `uafx/`
- Static analysis producer.
- Finds cross-entry UAF warning structure.
- Treat as the upstream producer, not the runtime layer.

### `uaf-bridge/`
- Canonical translator from static warning structure into deterministic bridge artifacts.
- Main stages:
  - `extractor/`
  - `mapping/`
  - `smt/`
  - `runtime/`
- Core contract:
  - raw warning or bridge export -> `candidate.json`
  - `candidate.json` -> `witness_plan.json`
  - `candidate.json` + `witness_plan.json` -> `witness.syz`
  - `candidate.json` + `witness_plan.json` -> `mock_seed.json`

### `mock/`
- Dynamic consumer of bridge output.
- Main responsibilities:
  - import bridge seed into a seeded workdir
  - validate runtime prerequisites
  - launch the seeded Healer workflow
- Main areas:
  - `tools/`
  - `bridge_seed/`
  - `scripts/`
  - `healer_fuzzer/`
  - `syz_wrapper/`

### `plans/`
- Short-lived task plans and validation reports.
- Read `plans/current.md`, `plans/repo-map.md`, and `plans/validation-report.md` before non-trivial changes.

### `context/`
- Durable status and known blockers.
- Read `context/current-status.md` and `context/known-issues.md` before changing behavior or claiming support.

### `docs/ai/`
- AI/operator-facing instructions and workflow notes.

## System Boundaries

### Artifact boundary
Do not break this pipeline:

`warning -> candidate.json -> witness_plan.json -> witness.syz / MOCK seed`

### Determinism boundary
- Everything up to the dynamic runtime stage should stay deterministic and reviewable.
- Do not hide unsupported cases behind heuristics that silently broaden support.

### Truthfulness boundary
- “Validated” only means:
  - the real arm64 KVM launch path was exercised
  - or the exact blocker was hit after earlier stages succeeded

## Current Supported Workflow

### Strongest supported path
- Narrow arm64 KVM workflow
- Bridge artifact generation
- MOCK seed preparation
- Seeded KVM startup path

### Important limits
- Witness support is a narrow KVM subset, not general syzkaller synthesis.
- Harness support is a narrow timer-family slice, not general harness generation.
- Full launch still requires real runtime assets and a Linux-capable syzkaller tree.

## Operator Workflow

### 1. Bridge environment
```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/uaf-bridge
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
PYTHON="$PWD/.venv/bin/python" bash scripts/run_end_to_end_kvm_demo.sh
```

Notes:
- Bridge scripts now choose the first interpreter that actually passes `scripts/check_env.py`.
- You can still pin the interpreter explicitly with `PYTHON=/absolute/path/to/python`.

### 2. MOCK seed preparation
```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock
bash scripts/prepare_kvm_seed.sh
```

Expected outputs:
- `seed_workdir/input/*.prog`
- `seed_workdir/relations/bridge_seed.relations`
- `seed_workdir/bias.json`

### 3. Syzkaller / Healer build
```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock
cargo build --release
export SYZ_DIR="$PWD/target/release/syz-bin"
```

Important:
- On Linux, this is the intended local build path.
- On macOS, `mock/syz_wrapper` now fails fast if it cannot build `linux/arm64/syz-executor`.
- If the host cannot produce a usable arm64 `SYZ_DIR`, use a Linux-built syzkaller tree and point `SYZ_DIR` at it.

### 4. Local runtime preflight
```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock
bash scripts/check_kvm_fuzz_prereqs.sh <arm64_disk_image> <ssh_key> <arm64_kernel_image>
```

This checks:
- disk image
- SSH key
- kernel image
- seed workdir
- relations file
- bias file
- syzkaller layout

### 5. Remote target preflight
```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock
bash scripts/check_remote_target.sh \
  --mode both \
  --target-host <host> \
  --ssh-key <ssh_key> \
  --syz-dir "$SYZ_DIR"
```

This checks:
- SSH connectivity
- writable remote temp space
- readable `dmesg`
- remote `gcc` for harness mode
- local `syz-executor` and `syz-execprog` availability for witness mode

### 6. Dry-run first
```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock
bash scripts/run_kvm_seed_fuzz.sh --dry-run <arm64_disk_image> <ssh_key> <arm64_kernel_image>
```

### 7. Real short run
```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock
bash scripts/run_kvm_seed_fuzz.sh --max-seconds 600 <arm64_disk_image> <ssh_key> <arm64_kernel_image>
```

## Maintenance Rules For OpenClaw
- Preserve the artifact flow and schema names.
- Do not silently change field names or ordering semantics.
- Prefer the smallest safe diff.
- Update `plans/current.md` before non-trivial edits.
- Run the smallest relevant checks first.
- When blocked by environment, fail early and report the exact stage and blocker.
- Do not claim broader support than the repo actually validates.

## What To Read Before Maintenance
- `AGENTS.md`
- `plans/current.md`
- `plans/repo-map.md`
- `plans/validation-report.md`
- `context/current-status.md`
- `context/known-issues.md`
- `README.md`
- `mock/README.md`
- `uaf-bridge/README.md`

## What Counts As Success
- The bridge demo succeeds.
- MOCK seed preparation succeeds.
- A Linux-capable `SYZ_DIR` is available.
- Preflight scripts pass with real runtime assets.
- `run_kvm_seed_fuzz.sh --dry-run` succeeds.
- A real seeded run starts, or an exact blocker is reported before that point.

## What OpenClaw Must Not Do
- Do not redesign the pipeline.
- Do not widen support claims beyond narrow arm64 KVM.
- Do not delete scripts or smoke paths just because they look auxiliary.
- Do not change candidate or witness schemas without explicit downstream review.
