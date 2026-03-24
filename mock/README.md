# MOCK

We open source the prototype of Mock here. Mock is a Linux kernel fuzzer that can learn the contextual dependencies in syscall sequences and then generate context-aware test cases. In this way, Mock improves the input quality and explore deeper space of kernels. More details can be found in [our paper](https://www.ndss-symposium.org/ndss-paper/mock-optimizing-kernel-fuzzing-mutation-with-context-aware-dependency/) from NDSS'24.

# Installation

As Mock is built upon [Healer](https://github.com/SunHao-0/healer), please follow the [instructions](https://github.com/SunHao-0/healer/blob/main/README.md) to prepare necessary toolchains. Image and kernel preparation can be found in this [document](https://github.com/google/syzkaller/blob/master/docs/linux/setup_ubuntu-host_qemu-vm_x86-64-kernel.md).

Besides, the training component is written in Python and interacts with the fuzzing component via http. Therefore, Python packages should be installed.
```
> pip3 install numpy django 
# if cuda is available
> pip3 install torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cu113
```

Once all the required tools have been installed, Mock can be easily built using the following command. It may some take to prepare the Rust bindings for Libtorch, [tch-rc](https://github.com/LaurentMazare/tch-rs), on which Mock depends.
```
> cargo build --release
```
You can find Mock and the patched Syzkaller binary tree under `target/release/syz-bin` after a successful release build. Set `SYZ_DIR` to that path, or pass `--syz-dir`, if you want the startup scripts to use a different syzkaller tree.

On macOS hosts, `cargo build --release` may still stop short of a usable arm64 KVM `SYZ_DIR` because local `linux_arm64/syz-executor` builds are not supported there. When that happens, treat it as an environment blocker and point `SYZ_DIR` at a Linux-built syzkaller tree instead of claiming the path is locally runnable.

# Usage

## Seed-guided arm64 KVM workflow

This repo now supports a practical bridge-guided workflow:

1. **UAFX** finds static arm64 KVM candidate structure.
2. **uaf-bridge** normalizes and solves that structure into `mock_seed.json`.
3. **MOCK** imports `mock_seed.json` into:
   - initial KVM-focused corpus programs
   - extra relation-bias hints
   - a bias summary for mutation policy / auditability
4. **healer** runs fuzzing with:
   - `-i <seeded input dir>`
   - `-R <bridge-seed relations file>`
   - `--arch arm64`

This preserves the KVM setup prefix (`/dev/kvm -> CREATE_VM -> CREATE_VCPU`), keeps KVM syscall-family focus, and prefers concurrency for `Con` flow seeds.

## Verifier support matrix

- **Verdict layer**: current verdicts are based on crash-text parsing plus candidate frame matching. This is honest but narrow; it does not claim full semantic crash triage.
- **Witness execution**: current witness mode expects a narrow runnable arm64 KVM witness and uploads local `syz-executor` / `syz-execprog` from `--syz-dir` to the remote target.
- **Harness execution**: current harness mode only supports the arm64 KVM timer close-vs-run family (`kvm_timer_vcpu_terminate` vs `kvm_timer_should_fire` via `kvm_vcpu_ioctl`).
- **Unsupported cases**: broader KVM device/IRQ template families, non-KVM candidates, and candidates outside the narrow timer harness family fail explicitly instead of silently falling back.

### One-command seed preparation

```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock
bash scripts/prepare_kvm_seed.sh
```

That will:
- run the bridge end-to-end demo
- import `uafx_kvm_mock_seed.json`
- create `seed_workdir/input/*.prog`
- create `seed_workdir/relations/bridge_seed.relations`
- create `seed_workdir/bias.json`

### Check startup prerequisites

This validates the runtime assets before you spend time on a dry-run or a real fuzzing job:

```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock
export SYZ_DIR="$PWD/target/release/syz-bin"
bash scripts/check_kvm_fuzz_prereqs.sh <arm64_disk_image> <ssh_key> <arm64_kernel_image>
```

The checker verifies:
- disk image path
- SSH key path
- kernel image path
- seed input dir
- seed relations file
- bridge bias file
- syzkaller layout and the expected `linux_arm64/syz-executor`

It also reports whether the optional Django model manager is reachable at `127.0.0.1:8000`.

### Check remote witness / harness prerequisites

Run this before PR3/PR4 witness or harness execution:

```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock
export SYZ_DIR="$PWD/target/release/syz-bin"
bash scripts/check_remote_target.sh \
  --mode both \
  --target-host <host> \
  --ssh-key <ssh_key>
```

What it checks:
- SSH connectivity
- writable remote temp dir
- readable `dmesg`
- remote `gcc` for harness mode
- local `syz-executor` and `syz-execprog` for witness mode

Current witness mode copies syzkaller executables from the local machine, so the remote target only needs to accept SSH/SCP and permit execution from the writable temp dir.

### Dry-run first

This is the recommended first startup step. It validates the seeded configuration, writes `output-seeded/debug-summary.json`, and does not boot fuzzing:

```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock
export SYZ_DIR="$PWD/target/release/syz-bin"
bash scripts/run_kvm_seed_fuzz.sh \
  --dry-run \
  <arm64_disk_image> \
  <ssh_key> \
  <arm64_kernel_image>
```

You can pass a custom seed or output location if needed:

```bash
bash scripts/run_kvm_seed_fuzz.sh \
  --dry-run \
  --seed-workdir ./seed_workdir \
  --output-dir ./output-seeded \
  --syz-dir "$PWD/target/release/syz-bin" \
  <arm64_disk_image> \
  <ssh_key> \
  <arm64_kernel_image>
```

### Run a short seeded smoke run

This starts the actual seeded fuzzing workflow after the prereq checker passes:

```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock
export SYZ_DIR="$PWD/target/release/syz-bin"
bash scripts/run_kvm_seed_fuzz.sh \
  --max-seconds 600 \
  <arm64_disk_image> \
  <ssh_key> \
  <arm64_kernel_image>
```

The older `scripts/run_kvm_seeded_fuzz.sh` entrypoint is still available as a compatibility shim, but `run_kvm_seed_fuzz.sh` is the canonical script now.

### Narrow end-to-end smoke foundations

The repo-root smoke helpers encode the intended golden path for the currently supported witness and harness slices:

```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin
bash scripts/e2e_witness_smoke.sh
bash scripts/e2e_harness_smoke.sh
```

They can stop at preflight or artifact generation when a real target is unavailable, but they document the exact workflow for the currently supported verifier paths.

### Equivalent direct healer dry-run

```bash
cargo run --release -p healer_fuzzer --bin healer -- \
  --arch arm64 \
  --bridge-bias ./seed_workdir/bias.json \
  -d <arm64_disk_image> \
  --ssh-key <ssh_key> \
  -k <arm64_kernel_image> \
  -S ./target/release/syz-bin \
  -i ./seed_workdir/input \
  -R ./seed_workdir/relations/bridge_seed.relations \
  -o ./output-seeded \
  --dry-run \
  --debug-summary-json ./output-seeded/debug-summary.json
```

### Equivalent direct healer smoke run

```bash
cargo run --release -p healer_fuzzer --bin healer -- \
  --arch arm64 \
  --bridge-bias ./seed_workdir/bias.json \
  -d <arm64_disk_image> \
  --ssh-key <ssh_key> \
  -k <arm64_kernel_image> \
  -S ./target/release/syz-bin \
  -i ./seed_workdir/input \
  -R ./seed_workdir/relations/bridge_seed.relations \
  -o ./output-seeded \
  --max-seconds 600
```

### Why this works

The importer translates `mock_seed.json` into artifacts that MOCK already knows how to use:
- **input programs** become initial corpus entries
- **relations** bias future call insertion toward KVM-focused sequences
- **collision preference** is naturally aligned with executor defaults (`FLAG_COLLIDE`)

This is still **structural guidance**, not exact KVM semantic state synthesis.

### Optional model manager

The Django model manager is **not required** for:
- bridge seed generation
- seed preparation
- prerequisite checking
- seeded dry-run
- short seeded startup

It is only needed if you want the background language-model training endpoint to be reachable during longer fuzzing runs. Start it separately if you need that capability:

```
> cd $MOCK_ROOT/tools/model_manager
> python3 manage.py runserver
```

If `target/release/syz-bin` does not exist yet, either:
- build locally and ensure the syzkaller build prerequisites are installed: `wget` or `curl`, `sha384sum`, `unzip`, `patch`, `make`, and `go`
- or point `SYZ_DIR` / `--syz-dir` at an existing compatible syzkaller tree

## Bridge-seed importer

Bridge-specific logic is intentionally isolated in:

- `bridge_seed/schema.py`
- `bridge_seed/importer.py`
- `bridge_seed/corpus.py`
- `bridge_seed/policy.py`
- `tools/import_bridge_seed.py`

This keeps raw UAFX/bridge concerns out of generic fuzzer internals.

## Corpus histogram / seeded-vs-unseeded comparison

```bash
python3 tools/corpus_histogram.py ./seed_workdir
python3 tools/corpus_histogram.py ./output-unseeded ./output-seeded
python3 tools/corpus_histogram.py ./output-seeded --json
```

## Runtime corpus prefix metrics

Use this tool when you want runtime-visible evidence of whether a corpus preserves the KVM setup prefix and trigger-side KVM focus:

```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock
python3 tools/corpus_prefix_metrics.py ./output-seeded
python3 tools/corpus_prefix_metrics.py ./output-seeded --json
python3 tools/corpus_prefix_metrics.py ./output-unseeded ./output-seeded
python3 tools/corpus_prefix_metrics.py ./output-unseeded ./output-seeded --json
```

It accepts either:
- a direct corpus dir of program files
- or a fuzzer output dir containing `corpus/`

Single-corpus mode reports:
- program and syscall counts
- KVM-related syscall percentage
- exact setup-prefix survival for the first 1/2/3 calls
- trigger-family presence counts
- per-family KVM counts
- top syscall histogram

Compare mode reports seeded-minus-unseeded deltas for:
- program and syscall counts
- KVM-related totals and percentage
- exact prefix survival
- trigger-family program presence
- per-family KVM counts

## One-command seeded vs unseeded compare

Run a short unseeded job, a short seeded job, then emit comparison artifacts in one place:

```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock
bash scripts/run_seeded_vs_unseeded_compare.sh <arm64_disk_image> <ssh_key> <arm64_kernel_image> 600
```

Optional fifth argument overrides the output base directory:

```bash
bash scripts/run_seeded_vs_unseeded_compare.sh <arm64_disk_image> <ssh_key> <arm64_kernel_image> 600 ./output-compare
```

The script clears and recreates these subdirectories under the output base before running:
- `seed_workdir/`
- `unseeded/`
- `seeded/`
- `comparison/`

Artifacts written under `comparison/`:
- `unseeded_metrics.json`
- `seeded_metrics.json`
- `delta.json`
- `report.txt`

`report.txt` is human-readable. The JSON artifacts are deterministic and meant for inspection or later comparison.

## Testing

```bash
cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock
PYTHONPATH=. python3 -m unittest tests/test_bridge_seed_import.py tests/test_corpus_histogram.py tests/test_corpus_prefix_metrics.py tests/test_startup_workflow.py
bash -n scripts/prepare_kvm_seed.sh
bash -n scripts/check_kvm_fuzz_prereqs.sh
bash -n scripts/run_kvm_seed_fuzz.sh
bash -n scripts/run_kvm_seeded_fuzz.sh
bash -n scripts/run_seeded_vs_unseeded_compare.sh
# Optional cargo-backed dry-run test:
RUN_CARGO_DRY_RUN_TEST=1 PYTHONPATH=. python3 -m unittest tests/test_dry_run_summary.py
# Optional Rust unit tests when the syzkaller build prerequisites are installed:
cargo test -p syz_wrapper path
```

# Citation
```
@inproceedings{
    author = {Jiacheng, Xu and Xuhong, Zhang and Shouling, Ji and Yuan, Tian and Binbin, Zhao and Qinying, Wang and Peng, Cheng and Jiming, Chen}, 
    title = {MOCK: Optimizing Kernel Fuzzing Mutation with Context-aware Dependency},
    booktitle = {31st Annual Network and Distributed System Security Symposium, {NDSS} 2024, San Diego, California, USA, February 26 - March 1, 2024}, 
    publisher = {The Internet Society},
    year = {2024}, 
}
```
