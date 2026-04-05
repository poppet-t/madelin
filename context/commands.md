# Commands

## Read and map repo
- tree -L 3
- find . -maxdepth 3 -type f | sort

## Existing bridge validation
- python3 -m uaf-bridge.extractor
- python3 uaf-bridge/smt/solve_candidate.py
- python3 uaf-bridge/runtime/emit_witness_syz.py

## Backend schema validation
- python3 backend/syz-guided/state_model/validate_state_model.py <path>
- python3 -m pytest backend/syz-guided/tests/test_state_model.py

## Seed generation smoke
- python3 backend/syz-guided/seedgen/synthesize_seeds.py --candidate out/.../candidate.json --witness out/.../witness_plan.json
- bash backend/syz-guided/scripts/smoke_seedgen.sh

## Campaign smoke
- bash backend/syz-guided/scripts/smoke_campaign.sh

## Triage smoke
- bash backend/syz-guided/scripts/smoke_triage.sh

## VM validator (macOS TCG or Linux KVM)
- bash backend/syz-guided/scripts/smoke_vm_validator.sh

## io_uring real-runtime campaign (arm64 Linux VM)
- bash backend/syz-guided/scripts/run_io_uring_vm_campaign.sh --syz-execprog <path> --syz-executor <path> [--threaded] [--procs 2] [--timeout-sec 90] [--out-dir out/io_uring-runtime/latest]

## io_uring unit tests
- python3 backend/syz-guided/tests/test_io_uring_lane.py -v
- python3 backend/syz-guided/tests/test_io_uring_verdict.py -v
- python3 backend/syz-guided/tests/test_io_uring_seedgen.py -v
- python3 backend/syz-guided/tests/test_io_uring_symbols.py -v

## net (nf_tables/netfilter) real-runtime campaign (arm64 Linux VM)
- bash backend/syz-guided/scripts/run_net_vm_campaign.sh --kernel syzkaller-runtime-export/kernel-export/nftables-enabled-Image --disk-image syzkaller-runtime-export/arm64-live-ready.qcow2 --ssh-key out/net-runtime/live-preflight-probe/id_rsa --guest-syz-execprog-path /root/syz-execprog --guest-syz-executor-path /root/syz-executor [--threaded] [--procs 1] [--timeout-sec 180] [--ssh-port 10022] [--repro-attempts 3] [--extended-rounds 0] [--out-dir out/net-runtime/live-YYYYMMDD-HHMMSS]
- Inspect strict preflight: `cat out/net-runtime/latest/preflight/preflight_summary.json`
- Inspect incremental strict-preflight progress: `cat out/net-runtime/latest/preflight/preflight_progress.json`
- Inspect final verdict: `cat out/net-runtime/latest/runtime/final_verdict.json`
- Inspect repro summary: `find out/net-runtime/latest/repro -name repro_summary.json -maxdepth 3 -print -exec cat {} \;`
- Export guest-resident linux/arm64 tooling back to the host: `bash backend/syz-guided/scripts/stage_arm64_guest_tooling.sh --ssh-key out/net-runtime/live-preflight-probe/id_rsa --ssh-port 10022 --out-dir out/net-runtime/guest-tools/linux-arm64`
- Latest repaired-overlay probe: `bash backend/syz-guided/scripts/run_net_vm_campaign.sh --kernel syzkaller-runtime-export/kernel-export/nftables-enabled-Image --disk-image /tmp/madelin-nft-debug2.qcow2 --ssh-key out/net-runtime/live-preflight-probe/id_rsa --single-seed-only --boot-timeout 240 --out-dir out/net-runtime/live-single-seed-nftables-overlaytest-6`

## net unit tests
- python3 backend/syz-guided/tests/test_net_lane.py -v
- python3 backend/syz-guided/tests/test_net_verdict.py -v
- python3 backend/syz-guided/tests/test_net_seedgen.py -v
- python3 backend/syz-guided/tests/test_net_symbols.py -v

## Linux KVM host preflight
- bash backend/syz-guided/scripts/check_linux_kvm_host.sh --kernel <path> --disk <path> --ssh-key <path>

## Linux KVM one-shot seed execution
- bash backend/syz-guided/scripts/run_linux_kvm_one_shot.sh --kernel <path> --disk <path> --ssh-key <path> --syz-execprog <path> --syz-executor <path> --prog <path> --out-dir <path>

## Linux KVM bounded syz-manager campaign
- bash backend/syz-guided/scripts/run_linux_syz_manager.sh --config <path> --out-dir <path> [--timeout 600]

- Single-seed-only TCG probe with default replacement image + guest tooling: `bash backend/syz-guided/scripts/run_net_vm_campaign.sh --kernel syzkaller-runtime-export/Image --ssh-key out/net-runtime/live-preflight-probe/id_rsa --single-seed-only --out-dir out/net-runtime/live-single-seed-operator-3`
- Inspect the exact blocker from the latest single-seed attempt: `cat out/net-runtime/live-single-seed-operator-3/preflight/preflight_summary.json`
