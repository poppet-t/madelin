# Validation Report

## Summary
This session moved the arm64 KVM workflow from artifact-only confidence to a partially exercised launch path. The bridge side now passes preflight, bridge CLI tests, and the end-to-end bridge demo. MOCK-side startup tests and seed preparation also pass. The remaining blocker is now fail-fast on this macOS host: `mock/syz_wrapper` aborts immediately with an explicit message that darwin cannot build the required `linux/arm64 syz-executor` locally for the arm64 KVM workflow, so the repo cannot honestly claim a runnable arm64 KVM launch from this machine.

## Commands Run
- `python3 uaf-bridge/scripts/check_env.py`
- `cd /Users/CJ/Desktop/Kernel-stuff/madelin/uaf-bridge && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'`
- `cd /Users/CJ/Desktop/Kernel-stuff/madelin/uaf-bridge && .venv/bin/python scripts/check_env.py`
- `cd /Users/CJ/Desktop/Kernel-stuff/madelin/uaf-bridge && .venv/bin/python -m pytest -q tests/test_bridge_python_selection.py tests/test_check_env.py tests/test_cli_integration.py tests/test_emit_witness_syz.py tests/test_export_mock_seed.py tests/test_validate_witness.py`
- `cd /Users/CJ/Desktop/Kernel-stuff/madelin/uaf-bridge && bash scripts/run_end_to_end_kvm_demo.sh`
- `cd /Users/CJ/Desktop/Kernel-stuff/madelin && python3 -m unittest mock.tests.test_startup_workflow mock.tests.test_remote_target_check`
- `cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock && bash scripts/prepare_kvm_seed.sh`
- `cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock && cargo build --release`
- `cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock/target/release/build/syz_wrapper-735a785e24c7dd02/out/syzkaller-169724fe58e8d7d0b4be6f59ca7c1e0f300399e1 && env TARGETOS=linux TARGETARCH=arm64 TARGETVMARCH=arm64 make executor execprog repro symbolize`
- `cd /Users/CJ/Desktop/Kernel-stuff/madelin/mock/target/release/build/syz_wrapper-735a785e24c7dd02/out/syzkaller-169724fe58e8d7d0b4be6f59ca7c1e0f300399e1 && patch --dry-run -p1 < sysgen.diff`

## Results
- `python3 uaf-bridge/scripts/check_env.py` failed first under the system interpreter because `jsonschema`, `z3`, and `pytest` were missing.
- The local `uaf-bridge/.venv` install succeeded, and `uaf-bridge/.venv/bin/python uaf-bridge/scripts/check_env.py` then passed.
- The bridge CLI tests passed under the local bridge venv.
- `bash uaf-bridge/scripts/run_end_to_end_kvm_demo.sh` passed and produced `candidate.json`, `witness_plan.json`, `witness.syz`, `mock_seed.json`, adapter output, and proof artifacts.
- `python3 -m unittest mock.tests.test_startup_workflow mock.tests.test_remote_target_check` passed.
- `bash mock/scripts/prepare_kvm_seed.sh` passed and generated the seeded MOCK workdir.
- `cargo build --release` initially failed because `syz_wrapper` required `wget`.
- After adding the `curl` fallback, the build progressed further.
- The final `cargo build --release` now fails quickly with the explicit darwin-host blocker before attempting the longer syzkaller build path:
  `darwin hosts cannot build the required linux/arm64 syz-executor locally for the arm64 KVM workflow. Use a Linux-built SYZ_DIR or run this build on Linux. If you already have generated syzkaller JSON descriptions, set SKIP_SYZ_BUILD=1 and SYZ_SYS_DIR=<path>.`

## Environment Limits
- The system Python on this host does not have `jsonschema`, `z3`, or `pytest`.
- The bridge’s reusable `.venv_sys` is not a trustworthy default for this session; the local `.venv` was required to validate the bridge path cleanly.
- This is a macOS host, and the syzkaller build gate now fails immediately because the required `linux/arm64/syz-executor` cannot be produced locally here.
- No arm64 disk image, SSH key, or arm64 kernel image was available in this session, so remote-target preflight, dry-run launch wiring, and the real seeded KVM launch were not exercised.

## Coverage Assessment
- Local correctness evidence: bridge environment preflight, bridge CLI tests, witness/seed emission, MOCK startup tests, and seed preparation all passed.
- Launch-path correctness evidence: the repo now reaches the syzkaller build boundary and fails fast there with a clear, actionable host limitation instead of pretending the arm64 runtime is ready.
- Full runnable end-to-end validation: not achieved in this session, because the final arm64 runtime prerequisite cannot be satisfied on this macOS host.

## Not Run
- `bash mock/scripts/check_kvm_fuzz_prereqs.sh <arm64_disk_image> <ssh_key> <arm64_kernel_image>`
- `bash mock/scripts/check_remote_target.sh --mode both --target-host <host> --ssh-key <ssh_key> --syz-dir "$SYZ_DIR"`
- `bash mock/scripts/run_kvm_seed_fuzz.sh --dry-run <arm64_disk_image> <ssh_key> <arm64_kernel_image>`
- `bash mock/scripts/run_kvm_seed_fuzz.sh --max-seconds 600 <arm64_disk_image> <ssh_key> <arm64_kernel_image>`
- The actual remote-capable arm64 KVM launch path

## Blocker
- Exact blocker: `mock/syz_wrapper` fails fast on this darwin host because it cannot build the required `linux/arm64/syz-executor` locally for the arm64 KVM workflow.
- Exact stage: `cargo build --release` in `mock/`, at the syzkaller build gate before the longer build path begins.
