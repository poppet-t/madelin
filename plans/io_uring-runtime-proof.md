# io_uring runtime lane — end-to-end proof

## What this proves

The io_uring target pack has a complete, tested, artifact-driven runtime validation path
from bridge fixture through to subsystem-aware verdict. This proof uses dry-run execution
(mock syz-execprog + synthetic KASAN crash) because real arm64 Linux VM execution requires
a live environment.

The proof demonstrates:
1. Exact inputs used
2. Full artifact chain emitted
3. Evidence artifacts answering "what ran and what was proven"
4. Subsystem-aware verdict classification
5. Clear distinction between what is proven and what is not

## Environment

```
Host:     macOS (Darwin 25.3.0, arm64)
Mode:     dry-run (mock syz-execprog, synthetic KASAN crash output)
Pack:     io_uring (maturity: runtime-validated(dry-run))
Target:   io-uring-arm64-v1
```

## Inputs

### Candidate (fixture)

```
candidate_id:   cand_2da2ab11b4a02071
subsystem:      io_uring
kernel_area:    fs/io_uring
object_type:    struct io_ring_ctx
loc0 (free):    io_ring_ctx_free @ io_uring/io_uring.c:2876
loc1 (use):     __io_submit_flush_completions @ io_uring/io_uring.c:2143
entry_func:     __do_sys_io_uring_enter
entry_kind:     io_uring_enter
```

Source fixture: `backend/syz-guided/tests/fixtures/packs/io_uring/candidate.json`

### Witness plan (fixture)

```
status:     sat
threads:    2 (free/cleanup on thread 0, use on thread 1)
barriers:   4 (escape→fetch, free→use ordering constraints)
predicates: io_uring_ring_ready, io_uring_files_registered (heuristic)
```

Source fixture: `backend/syz-guided/tests/fixtures/packs/io_uring/witness_plan.json`

## Artifact chain

### Step 1 — State model build

```
state_model_v1.json:
  subsystem:          io_uring
  target_family:      io-uring-arm64-v1
  phases.bootstrap:   [io_uring_setup]
  phases.configure:   [io_uring_register$IORING_REGISTER_FILES]
  phases.trigger:     [io_uring_enter, close$io_uring]
  immutable_prefix:   1 (io_uring_setup)
  resource_chain:     fd_ring (io_uring_setup → register/enter/close)

target_profile.json:
  focus_frames:       [io_ring_ctx_free, io_uring_release, percpu_ref_exit,
                       __io_submit_flush_completions, __do_sys_io_uring_enter, io_uring_enter]
  focus_files:        [io_uring/io_uring.c]
  preferred_syscalls: [io_uring_setup, io_uring_register$IORING_REGISTER_FILES,
                       io_uring_enter, close$io_uring]

relation_graph_v1.json:
  nodes: 5 (1 resource + 4 syscall)
  edges: resource_flow + must_precede constraints
```

Schema validation: **PASS** for all three artifacts.

### Step 2 — Seed synthesis

4 seed variants, all preserving the immutable bootstrap prefix (`io_uring_setup`):

| Seed | Calls | Prefix valid |
|------|-------|-------------|
| seed_enter_once.prog | setup → register → enter | ✓ |
| seed_enter_close.prog | setup → register → enter → close | ✓ |
| seed_poll_close.prog | setup → register → poll → close | ✓ |
| seed_dup_enter.prog | setup → register → dup → enter → close | ✓ |

Key properties verified:
- Bootstrap prefix (`io_uring_setup`) preserved in all 4 seeds
- Configure phase (`io_uring_register$IORING_REGISTER_FILES`) follows bootstrap in all seeds
- Suffix varies across variants (enter, enter+close, poll+close, dup+enter+close)
- Resource chain intact: `fd_ring` produced before consumed in all seeds

### Step 3 — Bounded campaign (dry-run)

```
iterations:       10
programs_scored:  10
best_score:       0.549
```

### Step 4 — Runtime lane execution (dry-run with synthetic crash)

**Synthetic KASAN crash used** (simulates the candidate's UAF):
```
BUG: KASAN: use-after-free in __do_sys_io_uring_enter+0x1a/0x30 io_uring/io_uring.c:2143
Read of size 8 at addr ffff0000deadbeef by task syz-executor/1234

Call Trace:
 __do_sys_io_uring_enter+0x1a/0x30
 io_uring_enter+0x11/0x22
 __io_submit_flush_completions+0x44/0x55

Freed by task 1232:
 io_ring_ctx_free+0x56/0x78
 io_uring_release+0x33/0x44
 percpu_ref_exit+0x12/0x20
```

### Step 5 — Evidence artifacts emitted

| Artifact | Size | Key content |
|----------|------|-------------|
| execution_trace_summary.json | 7610B | 4 seeds executed, 4 crashes, 0 timeouts, 4 trigger-phase-reached |
| preserved_prefix_report.json | 169B | 4/4 prefix valid (rate=1.00) |
| edge_coverage_summary.json | 149B | 4/4 resource chain intact (rate=1.00) |
| concurrency_window_report.json | 184B | threaded=true, overlap_window_attempted=true |
| candidate_alignment_report.json | 335B | best_match=1.00, uaf_type=true, subsystem_relevance=io_uring_teardown_use |
| runtime_verdict.json | 472B | verdict_class="candidate-correlated crash" |

Per-seed evidence also emitted:
- `seed_runs/<seed>/triage_report_v1.json` — per-seed triage with schema validation
- `seed_runs/<seed>/exec_stdout.txt` — syz-execprog output
- `seed_runs/<seed>/dmesg.txt` — kernel log capture
- `seed_runs/<seed>/seed_run_summary.json` — per-seed execution detail

### Step 6 — Runtime verdict

```json
{
  "verdict_class": "candidate-correlated crash",
  "reasons": [
    "At least one crash aligned with io_uring candidate signals and preserved prefix.",
    "Trigger phase was reached before the correlated crash."
  ],
  "signals": {
    "seeds_executed": 4,
    "crashes_detected": 4,
    "timeouts": 0,
    "trigger_phase_reached": 4,
    "best_match_score": 1.0,
    "any_uaf_type_match": true,
    "prefix_valid_rate": 1.0,
    "overlap_window_attempted": true
  }
}
```

### Step 7 — Subsystem-aware enrichment

The io_uring symbol enrichment correctly identified:
- Subsystem relevance: `io_uring_teardown_use` (both teardown and use frames present)
- Subsystem relevance score: 0.85
- Teardown frames: `io_ring_ctx_free`, `io_uring_release`
- Use frames: `__do_sys_io_uring_enter`, `io_uring_enter`, `__io_submit_flush_completions`
- Has teardown/use pair: true

## Commands to reproduce

```bash
# Unit tests (from backend/syz-guided/)
python3 tests/test_io_uring_lane.py -v          # 2 tests — runtime lane
python3 tests/test_io_uring_verdict.py -v        # 9 tests — all 6 verdict classes
python3 tests/test_io_uring_seedgen.py -v        # 9 tests — prefix preservation
python3 tests/test_io_uring_symbols.py -v        # 13 tests — symbol enrichment
python3 tests/test_packs_backend.py TestPackFixtures.test_io_uring_pack_fixture -v  # 1 test — dry-run proof

# Pack smoke (any platform)
bash backend/syz-guided/scripts/smoke_pack.sh --pack io_uring

# Real runtime campaign (arm64 Linux VM only)
bash backend/syz-guided/scripts/run_io_uring_vm_campaign.sh \
  --syz-execprog <path-to-syz-execprog> \
  --syz-executor <path-to-syz-executor> \
  [--bridge-export uaf-bridge/extractor/sample_uafx_io_uring_bridge_export.json] \
  [--out-dir out/io_uring-runtime/latest] \
  [--timeout-sec 90] \
  [--threaded] \
  [--procs 2]
```

## What is proven

| Claim | Status | Evidence |
|-------|--------|---------|
| Artifact chain is complete | **PROVEN** | All 6 evidence artifacts emitted from fixture inputs |
| Prefix preservation works for io_uring | **PROVEN** | 4/4 seeds preserve io_uring_setup prefix |
| Resource chain (fd_ring) is tracked | **PROVEN** | 4/4 seeds have producer→consumer ordering |
| Subsystem-aware triage classifies io_uring crashes | **PROVEN** | Symbol enrichment distinguishes teardown/use/lifecycle/unrelated |
| All 6 verdict classes are reachable | **PROVEN** | 9 unit tests cover all verdict paths |
| Campaign dry-run completes | **PROVEN** | 10 iterations, best_score=0.549 |
| Runtime lane emits correct verdict for synthetic crash | **PROVEN** | candidate-correlated crash with reasons |

## What is NOT proven

| Gap | Status | What's needed |
|-----|--------|---------------|
| Real syz-execprog execution on arm64 Linux VM | NOT VALIDATED | Linux host + QEMU/KVM + built syz-execprog |
| Real KASAN crash trigger from io_uring seeds | NOT VALIDATED | CONFIG_IO_URING=y + CONFIG_KASAN=y kernel |
| Coverage signal from kernel execution | NOT VALIDATED | KCOV + syzkaller coverage integration |
| syz-manager bounded campaign for io_uring | NOT VALIDATED | syz-manager + pack-specific config |
| Concurrency window actually exercised by kernel | NOT VALIDATED | Requires threaded syz-execprog with real kernel |

## How to run on a real arm64 Linux VM

Prerequisites:
- arm64 Linux host or VM with `/dev/kvm` (or software-only with TCG, slower)
- Kernel built with `CONFIG_IO_URING=y CONFIG_KASAN=y CONFIG_KCOV=y`
- syz-execprog and syz-executor built for `linux/arm64`
- Bootable arm64 disk image

Steps:
1. Run host preflight: `bash backend/syz-guided/scripts/check_linux_kvm_host.sh --kernel <path> --disk <path> --ssh-key <path>`
2. Run the full campaign: `bash backend/syz-guided/scripts/run_io_uring_vm_campaign.sh --syz-execprog <path> --syz-executor <path> --threaded`
3. Inspect `out/io_uring-runtime/latest/runtime/runtime_verdict.json` for the verdict
4. Inspect `out/io_uring-runtime/latest/runtime/execution_trace_summary.json` for per-seed detail
5. Check `out/io_uring-runtime/latest/runtime/candidate_alignment_report.json` for subsystem enrichment

## Test summary

| Test file | Count | Covers |
|-----------|-------|--------|
| test_io_uring_lane.py | 2 | Runtime lane execution + timeout classification |
| test_io_uring_verdict.py | 9 | All 6 verdict classes + signals + reasons |
| test_io_uring_seedgen.py | 9 | Prefix preservation, variant structure, resource chain |
| test_io_uring_symbols.py | 13 | Symbol tables, enrichment, subsystem classification |
| test_packs_backend.py (io_uring) | 1 | Full dry-run proof through campaign + triage |
| **Total** | **34** | |
