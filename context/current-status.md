# Current status

## Current truth

- The repo is organized as an artifact-centered pipeline.
- UAFX and bridge stages exist and must remain the canonical static producers.
- `backend/syz-guided/` is the canonical v1 syzkaller-based runtime backend.
- v1 is intentionally narrow. The legacy/initial validated slice is Linux arm64 KVM, and
  the repo is pivoting toward additional hardware-light target packs (io_uring, net, bpf, fs).
- Target-pack manifests now exist for `kvm`, `io_uring`, `net`, `bpf`, and `fs`.
- UAFX-first dry-run proofs now exist for `kvm`, `io_uring`, `net`, `bpf`, and `fs`.
- Candidate-aware triage and reproducible artifacts are mandatory backend properties.
- Bridge artifacts (candidate.json, witness_plan.json) are consumed read-only by the backend.
- All backend schemas validate against their JSON Schema definitions.
- The legacy `mock/` directory has been removed; `backend/syz-guided/` is the only runtime consumer.
- `syzkaller/` contains a clean upstream reference checkout (unmodified, no built binaries).
- `syzkaller-runtime-export/` preserves the arm64 KVM environment from the known working run.

## What is now true after v1 backend work

- `backend/syz-guided/` exists with full directory structure.
- Runtime schemas exist and validate (state_model_v1, target_profile, relation_graph_v1, triage_report_v1).
- State model generation is deterministic for the KVM fixture candidate.
- Seed synthesis emits 4 prefix-preserving .prog seeds for the KVM candidate.
- A bounded orchestrator exists with scoring, queuing, and campaign lifecycle.
- Candidate-aware triage emits structured reports with verdict classification.
- Prefix-safe mutation preserves bootstrap prefix and sticky calls.
- Relation guard validates resource chain integrity post-mutation.
- Full `uaf-bridge` pytest suite passes (`76` tests).
- Full `backend/syz-guided` unittest suite passes (`88` tests, including `30` vm_validator tests).
- Legacy backend smokes pass (`seedgen`, `campaign`, `triage`, `vm_validator`).
- Pack-aware backend smokes pass for `kvm`, `io_uring`, `net`, `bpf`, and `fs`.
- Root UAFX-first end-to-end dry-run proof passes for `kvm`, `io_uring`, `net`, `bpf`, and `fs`.
- syz-manager and syz-execprog build successfully from the in-repo syzkaller/ source tree
  (confirmed: `GOOS=linux GOARCH=arm64 go build ./syz-manager/` produces a valid 72M ELF).

## What is now true after vm_validator live execution

- QEMU TCG boots the arm64 kernel (`7.0.0-rc5-gbbeb83d3182a`) on macOS to SSH-ready.
- `arm64-standalone.qcow2` (11.5 GiB) replaces the broken overlay as the bootable image.
- Guest fstab fixed (removed stale BOOT/UEFI entries that caused emergency mode).
- syz-execprog (46M, built via Makefile with syscall descriptions) parses text `.prog` files directly.
- syz-executor (4.1M, compiled inside guest from source) connects to syz-execprog via flatrpc.
- Full execution pipeline proven: seed → syz-execprog → syz-executor → syscalls → dmesg → triage.
- KVM ioctls return EINVAL under TCG (no `/dev/kvm`) — expected, not a code issue.
- Triage pipeline produces correct `insufficient_data` verdict when no crash occurs.

## What is now true after Linux KVM preparation

- `plans/linux-kvm-runbook.md` provides the concrete execution plan for Linux KVM hosts.
- Three reusable Linux-side helper scripts exist (validated on macOS, ready for Linux):
  - `check_linux_kvm_host.sh` — host readiness preflight (PASS/WARN/FAIL summary)
  - `run_linux_kvm_one_shot.sh` — one-shot seed execution under QEMU/KVM
  - `run_linux_syz_manager.sh` — bounded syz-manager campaign launcher with timeout
- All three scripts fail honestly on macOS (report "not Linux" and exit nonzero).
- `vm_validator/` module (5 Python files, 30 unit tests) is fully implemented.

## What is now true after io_uring real-runtime lane (2026-04-02)

- `io_uring` is the first non-KVM pack with a complete real-runtime validation path.
- `backend/syz-guided/runtime/io_uring_lane.py` (385 lines) executes seeds per-seed with
  syz-execprog, collects dmesg, runs triage, and emits 6 machine-readable evidence artifacts.
- `backend/syz-guided/triage/io_uring_verdict.py` classifies runtime outcomes into 6
  verdict classes: candidate-correlated crash, probable unrelated crash, hang/stall/timeout,
  no crash but target path exercised, no meaningful target-path exercise, unsupported.
- `backend/syz-guided/triage/io_uring_symbols.py` provides io_uring-specific symbol tables
  (50+ lifecycle functions, 15+ source files) for subsystem-aware crash enrichment.
- `backend/syz-guided/scripts/run_io_uring_vm_campaign.sh` is an 8-step pipeline script
  from bridge export through runtime verdict on an ordinary arm64 Linux VM.
- `targets/io_uring/manifest.json` maturity upgraded from `scaffolded` to `runtime-validated(dry-run)`.
- Manifest now includes `enable_syscalls` and `runtime_config_hints` for syz-manager config.
- 34 io_uring-specific unit tests pass (2 lane + 9 verdict + 9 seedgen + 13 symbols + 1 pack fixture).
- Dry-run proof documented in `plans/io_uring-runtime-proof.md` with full artifact chain,
  evidence, and clear distinction between what is proven and what requires live execution.
- Evidence artifacts emitted: execution_trace_summary.json, preserved_prefix_report.json,
  edge_coverage_summary.json, concurrency_window_report.json, candidate_alignment_report.json,
  runtime_verdict.json.

## What is now true after net (nf_tables) live-lane hardening (2026-04-03)

- `backend/syz-guided/runtime/net_lane.py` now drives a real arm64 QEMU guest path instead of a host-only dry-run path.
- `backend/syz-guided/scripts/run_net_vm_campaign.sh` now requires guest inputs (`--kernel`, `--disk-image`, `--ssh-key`) and always creates `out/net-runtime/live-YYYYMMDD-HHMMSS/` plus `out/net-runtime/latest`.
- Strict live preflight is now unavoidable before any seed execution:
  - host checks: `qemu-system-aarch64`, `ssh`, `scp`, kernel/disk/key presence, arm64 ELF checks for `syz-execprog` and `syz-executor`
  - guest checks: non-interactive SSH, default-route networking, `/sys/kernel/debug`, debugfs mount, `console=ttyAMA0`, required kernel config, nf_tables/nfnetlink availability, `syz-execprog -coverfile`
- The net lane now runs in the required order:
  - single-seed validation
  - four-seed validation
  - short bounded campaign
  - optional extended fuzzing
- Per-seed live artifacts now include exact `.prog`, `syz-execprog` stdout/stderr, guest dmesg, layered evidence JSON, triage report, and per-seed verdict.
- Top-level live artifacts now include preflight summary, guest environment summary, phase summary, trigger reachability, crash signatures, repro summaries, minimization handoff, manual known-bug review template, and final verdict.
- Net verdicting is now split into three hard layers:
  - execution evidence
  - crash evidence
  - candidate evidence
- Repro handling is now real rather than notional:
  - crashing seeds are preserved
  - the lane reruns the seed multiple times under the same settings
  - reproducibility rate and per-attempt artifacts are recorded
- Known-bug hygiene is now explicit and blocking for novelty claims:
  - `manual_known_bug_review.json` is emitted
  - the final verdict only reaches `reproducible kernel bug candidate` after manual review marks `checked-novel`
  - unchecked results stay `novelty-unchecked bug candidate`
- The aggregate verdict classes now cover:
  - `environment/setup failure`
  - `target not reached`
  - `target reached, no crash`
  - `unrelated crash`
  - `candidate-correlated live crash`
  - `reproducible kernel bug candidate`
  - `novelty-unchecked bug candidate`
  - `known/likely-duplicate crash candidate`
- New targeted tests cover live preflight helpers, layered verdicts, repro classification, runtime artifact layout, manual novelty hygiene output, and live-mode failure classes.
- A real environment probe now exists under `out/net-runtime/live-script-probe/`: the full operator entrypoint reached strict preflight and exited with `environment/setup failure` against the archived `syzkaller-runtime-export` guest assets.
- The concrete blocker from that probe is guest readiness, not missing host plumbing: QEMU boots, but non-interactive SSH times out during banner exchange, so guest cmdline/config/debugfs/nf_tables checks cannot complete successfully.

## What is now true after guest-readiness work for net (2026-04-03, later pass)

- The original archived full-system guest path was too slow and unstable under arm64 QEMU TCG for the net live lane:
  the forwarded SSH port accepted host TCP, but the guest did not present a usable SSH session quickly enough for automation.
- The root cause was guest readiness, not missing keys:
  the old path depended on a heavy Ubuntu systemd boot and network bring-up before `sshd` was actually reachable.
- A replacement guest image now exists:
  `syzkaller-runtime-export/arm64-live-ready.qcow2`
  - it is a small overlay over `arm64-standalone.qcow2`
  - it contains `/root/madelin-guest-init.sh`
  - it is intended to boot with `init=/root/madelin-guest-init.sh`
- The minimal guest init performs:
  - remount root rw
  - mount proc/sysfs/devpts/debugfs
  - static slirp networking (`10.0.2.15/24`, gateway `10.0.2.2`)
  - `sshd` startup without relying on the full Ubuntu boot stack
- Host readiness detection is now stricter:
  - the VM path waits for a real SSH banner and a successful non-interactive command, not just an open TCP port
  - readiness attempts are recorded in `ssh-readiness-timeline.json`
- The net live lane can now use guest-resident tooling:
  - `/root/syz-execprog`
  - `/root/syz-executor`
  - host-side staging is optional rather than mandatory
- Guest tooling can be exported back to the host with:
  - `backend/syz-guided/scripts/stage_arm64_guest_tooling.sh`
- File staging now forces legacy scp mode (`scp -O`) to avoid SFTP hangs in the minimal guest environment.
- Real guest progress now reached:
  - non-interactive SSH success on the replacement image
  - direct one-seed staging into the guest
  - real guest-side `syz-execprog -executor=/root/syz-executor ...` invocation
- The next concrete live blocker is no longer guest setup failure:
  the first bounded seed execution can start, but the guest-side run can exceed the current per-seed timeout and must be classified/tuned as a seed execution timeout or stall.

## What remains for full v1 readiness

- Real KVM-triggered KASAN crash requires a Linux arm64 KVM host with `/dev/kvm`.
- One-shot seed execution under QEMU/KVM (using `run_linux_kvm_one_shot.sh`).
- Bounded syz-manager campaign (using `run_linux_syz_manager.sh`).
- Candidate-aware triage on real crash output.
- Repro wrapper end-to-end validation on real crash input.
- Coverage signal integration from syzkaller.
- FUSE-specific dry-run fixtures and backend phase/resource specialization remain scaffolded rather than validated.
- The next software-reachable target pack after the current four is `ublk`.
- io_uring real-runtime lane requires arm64 Linux VM execution for live validation.
- net real-runtime lane code path is live-guest capable; remaining work is environment-backed execution evidence on a prepared arm64 guest.
- bpf, fs packs could follow the io_uring/net runtime lane pattern.
- See `plans/linux-kvm-runbook.md` for the KVM step-by-step guide.
- See `plans/io_uring-runtime-proof.md` for the io_uring runtime proof.

## Migration status

- mock/ removed; remaining stale references are tracked and should be treated as cleanup work
  (see `plans/mock-removal-audit.md`).
- `plans/mock-removal-audit.md` classifies every remaining MOCK reference.
- `plans/syzkaller-runtime-proof.md` documents the syzkaller runtime selection path.
- `plans/validation-report.md` records full evidence for both smoke-level and
  environment-audit validation passes.

## net single-seed TCG pass (2026-04-03, latest pass)

- The net live operator path now defaults correctly for TCG guest work:
  - `syzkaller-runtime-export/arm64-live-ready.qcow2` is selected automatically when present and `--disk-image` is omitted.
  - guest-resident `/root/syz-execprog` and `/root/syz-executor` remain the default when host binaries are not provided.
  - `--single-seed-only` now stops the live lane after the first staged runtime step.
- The live runtime lane now emits explicit single-seed execution status artifacts (`seed_execution_status.json`) and stage summaries with classifications such as `timed-out`, `stalled`, `guest-exec-failure`, and `completed-no-crash`.
- A real guest-command transport bug was fixed in `runtime/net_lane.py`: remote commands are now quoted as a single `sh -lc ...` string before crossing SSH. This removed false negatives in guest cmdline/debugfs/network checks.
- The current hard blocker is no longer ambiguous timeout behavior. The current arm64 `syzkaller-runtime-export/Image` boots and passes guest readiness, but strict preflight still stops before the first seed because the kernel does not expose `nf_tables`/`nfnetlink` support required by the target.
- Evidence from `out/net-runtime/live-single-seed-operator-3/preflight/preflight_summary.json` shows:
  - guest cmdline/debugfs/network checks pass
  - `CONFIG_NF_TABLES` is still missing from the running kernel config
  - guest module/feature checks for `nfnetlink` and `nf_tables` fail
  - `nf_tables_exposed=false`
- Until the booted arm64 kernel is replaced with one that actually provides `nf_tables`, the live lane cannot honestly enter single-seed `nf_tables` execution.

## net nftables guest/runtime pass (2026-04-03, newest pass)

- The kernel-capability blocker is resolved for the current live experiments:
  `syzkaller-runtime-export/kernel-export/nftables-enabled-Image` boots and reports the expected
  `CONFIG_NETFILTER=y`, `CONFIG_NF_TABLES=y`, `CONFIG_KASAN=y`, `CONFIG_KCOV=y`, `CONFIG_DEBUG_FS=y`,
  `CONFIG_DEBUG_INFO=y`, and `CONFIG_KCOV_INSTRUMENT_ALL=y`.
- The old hardcoded `init=/root/madelin-guest-init.sh` path is no longer part of the live defaults.
- Guest boot/runtime integration was advanced by repairing a working overlay image path under TCG:
  - persistent host SSH keys were generated in the guest
  - root `authorized_keys` was installed
  - an early `madelin-live-ssh.service` now brings up static slirp networking and `sshd`
    before the heavy Ubuntu boot graph finishes
- The guest now demonstrably reaches real automation-ready SSH under the new kernel:
  - the boot console shows `Server listening on 0.0.0.0 port 22`
  - the host reaches accepted publickey sessions repeatedly during preflight
- Live preflight now gets materially farther than before:
  - `guest_runtime_prep` passes
  - `guest_arch` passes
  - kernel config validation passes
  - built-in netfilter features are now treated as valid built-in support rather than loadable-module failures
  - the preflight now emits `preflight_progress.json` so stalls are no longer opaque
- The current blocker has narrowed to guest command/tooling readiness, not guest boot:
  - some short non-interactive SSH command probes still time out under TCG
  - `serial_console` and `debugfs_path` checks are still receiving empty/timeout responses in preflight
  - the `NETLINK_NETFILTER` exposure probe is still failing
  - guest-side `/root/syz-execprog` and `/root/syz-executor` are not yet validating as usable linux/arm64 tooling for this repaired overlay path
- Current best evidence:
  - `out/net-runtime/live-single-seed-nftables-overlaytest-6/preflight/preflight_summary.json`
  - `out/net-runtime/live-single-seed-nftables-overlaytest-6/preflight/preflight_progress.json`
  - `out/net-runtime/live-single-seed-nftables-overlaytest-6/preflight/boot-console.log`
- The live lane still has not reached a trustworthy single-seed execution result yet because strict preflight is still failing on those remaining guest command/tooling checks.

## What is now true after lab-only net scaffolding (2026-04-04)

- The existing guest-backed `net` lane is now wrapped with additive **lab-only** reporting rather than a broader support claim.
- `backend/syz-guided/runtime/net_lane.py` now emits additive lab artifacts:
  - `runtime/kernel_provenance.json`
  - `runtime/source_frame_summary.json`
  - `runtime/blocker_report.json` when proof is not achieved
  - `runtime/lab_state.json`
  - `runtime/lab_run_bundle.json`
- The lab layer does not replace the existing runtime verdict schema; it maps existing verdicts into bounded lab-facing states:
  - `confirmed lab bug`
  - `candidate-correlated crash`
  - `no bug confirmed; exact blocker`
  - `patch candidate for reproduced lab bug`
- Per-run ranking inputs are now saved deterministically and locally:
  - `logs/ranking_input.json`
  - `logs/ranking_decision.json`
- Optional helper scripts now exist for bounded AI/operator prioritization:
  - `backend/syz-guided/scripts/rank_net_files.py`
  - `backend/syz-guided/scripts/rank_net_seeds.py`
- A dedicated lab-only target description now exists under:
  - `targets/net/lab/manifest.json`
  - `targets/net/lab/README.md`
  - `plans/net-lab-targets.md`
- This scaffolding is intentionally narrow:
  - it proves the repo can preserve deterministic artifacts and exact blocker reports for a lab-only net workflow
  - it does not claim broad net bug discovery, novelty detection, exploitability, or CVE discovery

## Net proof-mode run status (2026-04-04, latest)

- The new progress reporter is now active in the live net operator flow:
  - `backend/syz-guided/runtime/net_lane.py` writes `logs/progress.json`
  - `backend/syz-guided/scripts/run_net_vm_campaign.sh` renders milestone-based progress during the long runtime step
- The latest controlled proof run failed before guest boot and did not reach SSH readiness, preflight guest inspection, or seed execution.
- The exact blocker is now explicit in runtime artifacts:
  - `out/net-runtime/live-net-proof-with-progress/preflight/preflight_summary.json`
  - `out/net-runtime/live-net-proof-with-progress/runtime/blocker_report.json`
- The failure is not a kernel-capability issue and not a guest-exec issue.
  It is a disk image chain issue:
  - `/tmp/madelin-nft-debug2.qcow2` still references a missing backing file
  - missing backing path: `syzkaller-runtime-export/arm64.img`
- Because QEMU exited before creating the serial log, the run produced:
  - no boot console
  - no SSH readiness timeline beyond an empty list
  - no `preflight_progress.json`
  - no single-seed runtime artifacts
- Current truth:
  - the live lane and progress reporting are wired correctly
  - the next blocking prerequisite is a self-contained bootable qcow2 or a repaired qcow backing chain
