# net (nf_tables/netfilter) runtime lane — end-to-end proof

Status note (2026-04-03): this document remains the dry-run proof for the net pack fixture chain.
The authoritative live operator flow is now `backend/syz-guided/scripts/run_net_vm_campaign.sh`
plus `docs/ai/OPENCLAW-RUNBOOK.md`. Live guest execution claims still require captured
artifacts from a prepared arm64 kernel/disk/SSH environment.

## Networking family chosen: nf_tables via NETLINK_NETFILTER

### Why nf_tables

nf_tables is the best first networking target family for Madelin because:

1. **Software-reachable**: All operations go through `NETLINK_NETFILTER` sockets — no
   hardware, no passthrough, no KVM. Any arm64 Linux VM with `CONFIG_NF_TABLES=y` works.

2. **Explicit object lifecycle**: nft_set objects follow a clear create → configure →
   dump/query → delete → close lifecycle via netlink batch messages. This maps directly
   to Madelin's bootstrap → configure → trigger phase model.

3. **Known UAF surface**: The `struct nft_set` free/use pattern (free in
   `nf_tables_destroy_set`, use in `nf_tables_dump_set`) is a documented cross-entry
   UAF family. The UAFX candidate fixture models this exactly.

4. **Good fuzzability**: syzkaller has native `sendmsg$NFT_BATCH*`, `socket$NETLINK_NETFILTER`,
   and `recvmsg` syscall descriptions. Seeds can be synthesized directly from these.

5. **Concurrency window**: The delete+dump race (thread A destroys a set while thread B
   dumps it) is exercisable with threaded `syz-execprog` — no custom threading harness needed.

6. **Rich triage surface**: nf_tables has ~50 lifecycle functions across 15+ source files,
   with clear teardown/use frame pairs that enable subsystem-aware crash classification.

Alternatives considered:
- **rtnetlink**: Simpler but less interesting lifecycle (fewer cross-entry transitions)
- **generic netlink**: Too broad — no single candidate family to target
- **packet socket**: Good fuzz surface but fewer structured lifecycle edges
- **network namespace lifecycle**: Useful as a setup helper, not as a primary target

## What this proves

The net target pack has a complete, tested, artifact-driven runtime validation path
from bridge fixture through to subsystem-aware verdict. This proof uses dry-run execution
(mock syz-execprog + synthetic KASAN crash) because real arm64 Linux VM execution requires
a live environment.

The proof demonstrates:
1. Exact inputs used
2. Full artifact chain emitted
3. Evidence artifacts answering "what ran and what was proven"
4. Subsystem-aware verdict classification with net-specific symbol enrichment
5. Clear distinction between what is proven and what is not

## Environment

```
Host:     macOS (Darwin 25.3.0, arm64)
Mode:     dry-run (mock syz-execprog, synthetic KASAN crash output)
Pack:     net (maturity: runtime-validated(dry-run))
Target:   net-netfilter-arm64-v1
Family:   nf_tables object lifecycle via NETLINK_NETFILTER
```

## Inputs

### Candidate (fixture)

```
candidate_id:   cand_ca6bd5da811d1948
subsystem:      net
kernel_area:    net/netfilter
object_type:    struct nft_set
loc0 (free):    nf_tables_destroy_set @ net/netfilter/nf_tables_api.c:6123
loc1 (use):     nf_tables_dump_set @ net/netfilter/nf_tables_api.c:7441
entry_func:     nfnetlink_rcv_batch
entry_kind:     netlink_send
```

Source fixture: `backend/syz-guided/tests/fixtures/packs/net/candidate.json`

### Witness plan (fixture)

```
status:     sat
threads:    2 (free/cleanup on thread 0, use on thread 1)
barriers:   4 (escape→fetch, free→use ordering constraints)
predicates: nf_tables_set_allocated, nfnetlink_ready (heuristic)
```

Source fixture: `backend/syz-guided/tests/fixtures/packs/net/witness_plan.json`

## Artifact chain

### Step 1 — State model build

```
state_model_v1.json:
  subsystem:          net
  target_family:      net-netfilter-arm64-v1
  phases.bootstrap:   [socket$NETLINK_NETFILTER]
  phases.configure:   [sendmsg$NFT_BATCH_CREATE, sendmsg$NFT_BATCH_UPDATE]
  phases.trigger:     [recvmsg$NETLINK_DUMP, sendmsg$NFT_BATCH_DELETE, close$NETLINK_NETFILTER]
  immutable_prefix:   1 (socket$NETLINK_NETFILTER)
  resource_chain:     fd_nl (socket → sendmsg/recvmsg/close)

target_profile.json:
  focus_frames:       [nf_tables_destroy_set, nf_tables_dump_set,
                       nfnetlink_rcv_batch, nft_do_chain]
  focus_files:        [net/netfilter/nf_tables_api.c]
  preferred_syscalls: [socket$NETLINK_NETFILTER, sendmsg$NFT_BATCH_CREATE,
                       sendmsg$NFT_BATCH_UPDATE, recvmsg$NETLINK_DUMP,
                       sendmsg$NFT_BATCH_DELETE, close$NETLINK_NETFILTER]

relation_graph_v1.json:
  nodes: 8 (1 resource + 7 syscall)
  edges: resource_flow + must_precede constraints
```

Schema validation: **PASS** for all three artifacts.

### Step 2 — Seed synthesis

4 seed variants, all preserving the immutable bootstrap prefix (`socket$NETLINK_NETFILTER`):

| Seed | Calls | Lifecycle pattern |
|------|-------|-------------------|
| seed_dump_delete.prog | socket → create → update → dump → delete | dump+delete race window |
| seed_delete_close.prog | socket → create → update → delete → close | teardown sequence |
| seed_dump_close.prog | socket → create → update → dump → close | use-after-close |
| seed_update_dump_delete.prog | socket → create → update → update → dump → delete | extended lifecycle |

Key properties verified:
- Bootstrap prefix (`socket$NETLINK_NETFILTER`) preserved in all 4 seeds
- Configure phase (`sendmsg$NFT_BATCH_CREATE`, `sendmsg$NFT_BATCH_UPDATE`) follows bootstrap
- Suffix varies across variants (dump+delete, delete+close, dump+close, update+dump+delete)
- Resource chain intact: `fd_nl` produced before consumed in all seeds

### Step 3 — Bounded campaign (dry-run)

```
iterations:       10
programs_scored:  10
best_score:       0.750
```

### Step 4 — Runtime lane execution (dry-run with synthetic crash)

**Synthetic KASAN crash used** (simulates the candidate's UAF):
```
BUG: KASAN: use-after-free in nf_tables_dump_set+0x1a/0x30 net/netfilter/nf_tables_api.c:7441
Read of size 8 at addr ffff0000deadbeef by task syz-executor/1234

Call Trace:
 nf_tables_dump_set+0x1a/0x30
 nf_tables_getset+0x11/0x22

Freed by task 1232:
 nf_tables_destroy_set+0x56/0x78
```

### Step 5 — Evidence artifacts emitted

| Artifact | Key content |
|----------|-------------|
| execution_trace_summary.json | 4 seeds executed, 4 crashes, 0 timeouts, 4 trigger-phase-reached |
| preserved_prefix_report.json | 4/4 prefix valid (rate=1.00) |
| edge_coverage_summary.json | 4/4 resource chain intact (rate=1.00) |
| concurrency_window_report.json | threaded=true, overlap_window_attempted=true |
| candidate_alignment_report.json | best_match=1.00, uaf_type=true, subsystem_relevance=net_teardown_use |
| runtime_verdict.json | verdict_class="candidate-correlated crash" |

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
    "At least one crash aligned with net candidate signals and preserved prefix.",
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

The net symbol enrichment correctly identified:
- Subsystem relevance: `net_teardown_use` (both teardown and use frames present)
- Subsystem relevance score: 0.85
- Teardown frames: `nf_tables_destroy_set`
- Use frames: `nf_tables_dump_set`
- Has teardown/use pair: true
- Source file match: `net/netfilter/nf_tables_api.c`

## Commands to reproduce

```bash
# Unit tests (from repo root)
python3 backend/syz-guided/tests/test_net_lane.py -v          # 2 tests — runtime lane
python3 backend/syz-guided/tests/test_net_verdict.py -v        # 9 tests — all 6 verdict classes
python3 backend/syz-guided/tests/test_net_seedgen.py -v        # 9 tests — prefix preservation
python3 backend/syz-guided/tests/test_net_symbols.py -v        # 13 tests — symbol enrichment
python3 backend/syz-guided/tests/test_packs_backend.py TestPackFixtures.test_net_pack_fixture -v  # 1 test — dry-run proof

# Pack smoke (any platform)
bash backend/syz-guided/scripts/smoke_pack.sh --pack net

# E2E UAFX-first smoke (any platform)
bash scripts/e2e_target_pack_smoke.sh --pack net

# Real runtime campaign (arm64 Linux VM only)
bash backend/syz-guided/scripts/run_net_vm_campaign.sh \
  --syz-execprog <path-to-syz-execprog> \
  --syz-executor <path-to-syz-executor> \
  [--bridge-export uaf-bridge/extractor/sample_uafx_net_bridge_export.json] \
  [--out-dir out/net-runtime/latest] \
  [--timeout-sec 90] \
  [--threaded] \
  [--procs 2]
```

## What is proven

| Claim | Status | Evidence |
|-------|--------|---------|
| Artifact chain is complete | **PROVEN** | All 6 evidence artifacts emitted from fixture inputs |
| Prefix preservation works for nf_tables | **PROVEN** | 4/4 seeds preserve socket$NETLINK_NETFILTER prefix |
| Resource chain (fd_nl) is tracked | **PROVEN** | 4/4 seeds have producer→consumer ordering |
| Subsystem-aware triage classifies net crashes | **PROVEN** | Symbol enrichment distinguishes teardown/use/lifecycle/unrelated |
| All 6 verdict classes are reachable | **PROVEN** | 9 unit tests cover all verdict paths |
| Campaign dry-run completes | **PROVEN** | 10 iterations, best_score=0.750 |
| Runtime lane emits correct verdict for synthetic crash | **PROVEN** | candidate-correlated crash with reasons |
| nf_tables lifecycle exercised in seeds | **PROVEN** | 4 variants cover dump+delete, delete+close, dump+close, update+dump+delete |
| Delete+dump concurrency window modeled | **PROVEN** | concurrency_window_report shows overlap_window_attempted=true |

## What is NOT proven

| Gap | Status | What's needed |
|-----|--------|---------------|
| Real syz-execprog execution on arm64 Linux VM | NOT VALIDATED | Linux host + QEMU/KVM + built syz-execprog |
| Real KASAN crash trigger from nf_tables seeds | NOT VALIDATED | CONFIG_NF_TABLES=y + CONFIG_KASAN=y kernel |
| Coverage signal from kernel execution | NOT VALIDATED | KCOV + syzkaller coverage integration |
| syz-manager bounded campaign for net | NOT VALIDATED | syz-manager + net-specific config |
| Concurrency window actually exercised by kernel | NOT VALIDATED | Requires threaded syz-execprog with real kernel |
| Netlink message payloads triggering real nft_set operations | NOT VALIDATED | Requires syzkaller's NFT_BATCH message construction |

## How to run on a real arm64 Linux VM

Prerequisites:
- arm64 Linux host or VM with `/dev/kvm` (or software-only with TCG, slower)
- Kernel built with `CONFIG_NF_TABLES=y CONFIG_NETFILTER=y CONFIG_NF_TABLES_NETDEV=y CONFIG_KASAN=y CONFIG_KCOV=y`
- syz-execprog and syz-executor built for `linux/arm64`
- Bootable arm64 disk image

Steps:
1. Run host preflight: `bash backend/syz-guided/scripts/check_linux_kvm_host.sh --kernel <path> --disk <path> --ssh-key <path>`
2. Run the full campaign: `bash backend/syz-guided/scripts/run_net_vm_campaign.sh --syz-execprog <path> --syz-executor <path> --threaded`
3. Inspect `out/net-runtime/latest/runtime/runtime_verdict.json` for the verdict
4. Inspect `out/net-runtime/latest/runtime/execution_trace_summary.json` for per-seed detail
5. Check `out/net-runtime/latest/runtime/candidate_alignment_report.json` for subsystem enrichment

## Test summary

| Test file | Count | Covers |
|-----------|-------|--------|
| test_net_lane.py | 2 | Runtime lane execution + timeout classification |
| test_net_verdict.py | 9 | All 6 verdict classes + signals + reasons |
| test_net_seedgen.py | 9 | Prefix preservation, variant structure, resource chain |
| test_net_symbols.py | 13 | Symbol tables, enrichment, subsystem classification |
| test_packs_backend.py (net) | 1 | Full dry-run proof through campaign + triage |
| **Total** | **34** | |
