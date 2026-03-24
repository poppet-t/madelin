# v2 Architecture Plan: Candidate-Specific UAF Verifier

## What this plan is

A concrete phased plan to transform madelin from a "static-guided seed biaser for general fuzzing" into a "candidate-specific micro-environment verifier that proves, refutes, or narrows UAF hypotheses."

## What changes architecturally

**v1 (current):** candidate.json -> witness_plan.json -> mock_seed.json -> general fuzzer with better seeds
**v2 (target):** candidate.json -> witness_plan.json -> runnable_witness.syz -> micro-harness execution -> verdict.json

The three-layer split (UAFX / bridge / MOCK) is preserved. What changes is:
- The bridge emits a **runnable** witness, not a comment block
- MOCK gains a **focused execution mode** distinct from general fuzzing
- A new **verdict layer** closes the loop from runtime back to the candidate

## macOS-native constraint

The user runs macOS (Darwin 25.3.0, arm64). The system must run compactly on this machine.

What runs natively on macOS:
- All Python (bridge, verdict analysis, orchestration)
- Z3 solver
- Rust compilation (MOCK library code, tools)
- Crash report parsing and verdict generation
- Witness program generation

What requires a Linux target:
- Actual kernel execution (KVM ioctls, KASAN)
- syz-executor

Execution strategy: **local-generate, remote-execute, local-judge.**
- Generate all artifacts locally
- Execute via SSH against a Linux arm64 target (remote box, cloud VM, or local QEMU)
- Pull results back and judge locally
- The target is a thin execution endpoint, not a compute center

This keeps the macOS footprint to: Python + Rust + Z3 + SSH client. No local VMs required for the core workflow.

---

## Phase 0: Foundation (enforce existing bridge intent)

**Goal:** Make the current system actually respect what the bridge already emits, so Phase 1+ improvements have a measurable baseline.

**This is kvm-refinement-pass-1, already planned. Do it first.**

### 0.1 Enforce preserve_prefix_len in MOCK mutation
- Files: `mock/healer_core/src/bridge_bias.rs`, `mock/healer_core/src/mutation/seq.rs`
- The bridge emits `preserve_prefix_len: 3`. The mutator ignores it. Fix that.

### 0.2 Enforce keep_ordering_edges in MOCK mutation
- Files: same as 0.1
- The bridge emits `escape->fetch`, `free->use` ordering edges. The mutator can reorder past them. Fix that.

### 0.3 Add prefix survival metrics to dry-run output
- Files: `mock/healer_fuzzer/src/debug_summary.rs`
- After N mutations of a seed program, report what % retained the prefix and ordering.

### Verification
- `cd mock && cargo test -p healer_core`
- `cd mock && bash scripts/prepare_kvm_seed.sh`
- Histogram: 100% prefix survival after mutation

### Done when
- Mutation respects prefix and ordering
- Baseline metrics exist for comparison with later phases

---

## Phase 1: Verdict Layer

**Goal:** Given a crash report and a candidate, produce a structured verdict. This is the single most important missing piece. Without it, nothing downstream can be evaluated.

### 1.1 Crash report parser

New module: `mock/verdict/parse_crash.py`

Input: raw KASAN/kernel crash text (from `output-kvm-seeded/crashes/*/log*`)
Output: structured dict:
```python
{
    "crash_type": "use-after-free",      # or slab-out-of-bounds, null-deref, etc.
    "access": "read" | "write",
    "faulting_address": "0xffff...",
    "stack_frames": [
        {"function": "kvm_vcpu_ioctl", "file": "arch/arm64/kvm/arm.c", "line": 342},
        ...
    ],
    "free_stack": [...],                  # if KASAN reports it
    "alloc_stack": [...],                 # if KASAN reports it
    "raw": "..."
}
```

This parser handles KASAN report format. It is ~150 lines. No kernel source needed — just regex on crash text.

### 1.2 Crash matcher

New module: `mock/verdict/match_candidate.py`

Input: parsed crash + candidate.json
Output: match result:
```python
{
    "verdict": "CONFIRMED" | "REACHED_NO_CRASH" | "UNRELATED_CRASH"
                | "SETUP_FAILED" | "TIMING_INCONCLUSIVE" | "PATH_INFEASIBLE",
    "confidence": "high" | "medium" | "low",
    "evidence": {
        "loc0_match": True | False,       # free site function in crash free_stack?
        "loc1_match": True | False,       # use site function in crash stack?
        "crash_type_match": True | False, # is it actually a UAF?
        "subsystem_match": True | False,  # is it in arch/arm64/kvm/?
        "matched_frames": [...]
    }
}
```

Match logic:
- `CONFIRMED`: crash_type is UAF AND loc0 function in free_stack AND loc1 function in crash stack
- `UNRELATED_CRASH`: crash occurred but doesn't match loc0/loc1
- `REACHED_NO_CRASH`: execution log shows candidate entry functions were called, no crash
- `SETUP_FAILED`: execution log shows setup calls failed (ENODEV, fd=-1)
- `TIMING_INCONCLUSIVE`: both threads entered target functions, no crash after K runs
- `PATH_INFEASIBLE`: coverage shows entry functions never reached

This is ~200 lines. Pure string matching against stack traces.

### 1.3 Verdict emitter

New module: `mock/verdict/emit_verdict.py`

Input: candidate.json + match result + execution metadata
Output: `verdict.json`:
```json
{
    "candidate_id": "cand_1a2b3c4d",
    "verdict": "CONFIRMED",
    "confidence": "high",
    "evidence": { ... },
    "execution": {
        "runs": 47,
        "wall_seconds": 312,
        "crashes_total": 3,
        "crashes_matched": 1
    },
    "timestamp": "2026-03-22T14:30:00Z"
}
```

### 1.4 Wire into post-run

Modify `mock/scripts/run_kvm_seed_fuzz.sh` to:
1. After fuzzing completes, scan `output-kvm-seeded/crashes/`
2. Run crash matcher against the candidate that produced the seed
3. Write `verdict.json` to the output directory
4. Print verdict summary to stdout

### 1.5 Wire into proof bundle

Modify `uaf-bridge/proof/package_artifacts.py` to include `verdict.json` when available.

### Verification
- Unit tests with sample KASAN reports (real ones from kernel history)
- Test with known-UAF crash text + matching candidate -> CONFIRMED
- Test with unrelated crash text + candidate -> UNRELATED_CRASH
- Test with no crash + candidate -> REACHED_NO_CRASH

### Done when
- `verdict.json` is produced after every fuzzing run
- Verdict taxonomy covers all 6 states
- At least 3 real KASAN report samples are used in tests

---

## Phase 2: Runnable Witness Layer

**Goal:** Replace the pseudo-syz comment block with an actually executable syzkaller program that embodies the candidate's predicted UAF trigger sequence.

### 2.1 Syzkaller description harvester

New module: `uaf-bridge/mapping/syz_descriptions.py`

Problem: current templates emit `ioctl$KVM_ARM_VCPU_INIT(fd_vcpu, KVM_ARM_VCPU_INIT, &init)` with placeholder args. To be runnable, we need real argument shapes from syzkaller's type system.

Approach: parse syzkaller's `.txt` description files for KVM arm64 syscalls. These are already vendored in `mock/syz_wrapper/`. Extract:
- Argument types and valid ranges for each KVM ioctl
- Resource types (fd_kvm, fd_vcpu, etc.) and their producers
- Struct layouts for ioctl arguments

This is a one-time extraction that produces a `kvm_arm64_descriptions.json` used by the witness emitter. ~300 lines to parse the relevant syz descriptions.

### 2.2 Concrete witness emitter

Replace: `uaf-bridge/runtime/emit_witness_syz.py`

The new emitter produces an **actually parseable** syzkaller program. Not a comment block.

Input: candidate.json + witness_plan.json + kvm_arm64_descriptions.json
Output: `witness.syz` that syz-executor can run

Format (real syz program syntax):
```
r0 = openat$KVM(0xffffffffffffff9c, &AUTO='/dev/kvm\x00', 0x2, 0x0)
r1 = ioctl$KVM_CREATE_VM(r0, 0xae01, 0x0)
r2 = ioctl$KVM_CREATE_VCPU(r1, 0xae41, 0x0)
ioctl$KVM_ARM_VCPU_INIT(r2, 0xae02, &AUTO={0x0, 0x0, [0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0]})
ioctl$KVM_RUN(r2, 0xae80, 0x0)
```

Key properties:
- Uses real ioctl numbers (from kernel headers or syz descriptions)
- Uses syz resource syntax (`r0 =`, then `r0` as arg)
- Uses valid struct layouts
- Thread grouping when candidate flow is "Con"

Concurrency format for 2-thread witnesses:
```
# Thread 0: setup + escape
r0 = openat$KVM(...)
r1 = ioctl$KVM_CREATE_VM(r0, ...)
r2 = ioctl$KVM_CREATE_VCPU(r1, ...)
ioctl$KVM_ARM_VCPU_INIT(r2, ...)

# Thread 1: free + use (concurrent)
ioctl$KVM_RUN(r2, ...)
```

This is ~400 lines. The hard part is getting ioctl numbers and struct layouts right. Start with the ~15 KVM ioctls already in templates and expand.

### 2.3 Witness validator (local, no VM needed)

New module: `uaf-bridge/runtime/validate_witness.py`

Runs on macOS. Checks that the emitted witness.syz:
- Parses as valid syz program syntax
- Has correct resource flow (every fd used is previously opened)
- Uses real ioctl numbers
- Has correct struct sizes
- Thread assignments match witness plan

This catches errors before wasting execution time.

### 2.4 Witness executor wrapper

New script: `mock/scripts/run_witness.sh`

Simplified execution path for a single witness:
```bash
run_witness.sh --witness witness.syz --candidate candidate.json \
    <disk_image> <ssh_key> <kernel_image>
```

This:
1. Copies `witness.syz` + `syz-executor` to target via SSH
2. Runs the witness program N times with timing variation
3. Collects KASAN output
4. Runs verdict matcher
5. Emits `verdict.json`

No fuzzer loop. No corpus management. No mutation. Just: execute this specific program and tell me what happened.

### Verification
- Parse 5 real syz programs from syzkaller's corpus, confirm format match
- Generate witness for sample candidate, validate locally
- Dry-run witness executor (validate SSH/SCP commands without real target)

### Done when
- `witness.syz` is parseable by syz-executor
- Local validator catches malformed witnesses
- Witness executor produces verdict.json

---

## Phase 3: Micro-Harness Layer

**Goal:** For each candidate, generate a purpose-built C test program that directly exercises the predicted UAF path with controlled concurrency. This is the core of the verifier.

### 3.1 Harness template engine

New module: `uaf-bridge/harness/generate_harness.py`

Generates a standalone C program per candidate. Template structure:

```c
// Auto-generated UAF verification harness
// candidate_id: cand_1a2b3c4d
// predicted free: kvm_destroy_vcpu (arch/arm64/kvm/arm.c:342)
// predicted use:  kvm_vcpu_ioctl (arch/arm64/kvm/arm.c:891)

#include <fcntl.h>
#include <sys/ioctl.h>
#include <linux/kvm.h>
#include <pthread.h>
#include <unistd.h>

static int kvm_fd, vm_fd, vcpu_fd;

// Setup: establish KVM resource chain
static int setup(void) {
    kvm_fd = open("/dev/kvm", O_RDWR);
    if (kvm_fd < 0) return -1;
    vm_fd = ioctl(kvm_fd, KVM_CREATE_VM, 0);
    if (vm_fd < 0) return -1;
    vcpu_fd = ioctl(vm_fd, KVM_CREATE_VCPU, 0);
    if (vcpu_fd < 0) return -1;
    // ... candidate-specific setup from template
    return 0;
}

// Thread A: trigger free path
static void *thread_free(void *arg) {
    usleep(*(int*)arg);  // timing parameter
    // candidate-specific free-path syscalls
    close(vcpu_fd);  // or candidate-specific teardown
    return NULL;
}

// Thread B: trigger use path
static void *thread_use(void *arg) {
    usleep(*(int*)arg);  // timing parameter
    // candidate-specific use-path syscalls
    ioctl(vcpu_fd, KVM_RUN, 0);
    return NULL;
}

int main(int argc, char **argv) {
    int timing_us = argc > 1 ? atoi(argv[1]) : 0;
    if (setup() < 0) {
        printf("VERDICT: SETUP_FAILED\n");
        return 1;
    }
    pthread_t t1, t2;
    int delay_free = timing_us;
    int delay_use = 0;
    pthread_create(&t1, NULL, thread_free, &delay_free);
    pthread_create(&t2, NULL, thread_use, &delay_use);
    pthread_join(t1, NULL);
    pthread_join(t2, NULL);
    printf("VERDICT: REACHED_NO_CRASH\n");
    return 0;
}
```

The generator:
- Reads candidate.json for loc0/loc1, entry functions, flow type
- Reads witness_plan.json for thread assignments and ordering
- Selects the right ioctl sequences from the template library
- Inserts timing parameters as command-line arguments
- Emits compilable C with POSIX threads

This is ~500 lines of Python generating ~100-200 lines of C per candidate.

### 3.2 Cross-compiler support

The harness must compile for arm64 Linux (target) on macOS (host).

Add: `mock/scripts/build_harness.sh`

```bash
# Uses aarch64-linux-gnu-gcc (installable via brew)
# brew install aarch64-elf-gcc  (or use a cross toolchain)
aarch64-linux-gnu-gcc -static -O2 -pthread \
    -o harness_${CANDIDATE_ID} harness_${CANDIDATE_ID}.c
```

Alternative: compile on the target via SSH (simpler, no cross-compiler needed):
```bash
scp harness.c target:/tmp/
ssh target "gcc -O2 -pthread -o /tmp/harness /tmp/harness.c"
```

### 3.3 Timing sweep executor

New script: `mock/scripts/run_harness.sh`

```bash
run_harness.sh --harness harness.c --candidate candidate.json \
    --timing-range 0,100,1000,5000,10000,50000 \
    --runs-per-timing 100 \
    <target_host> <ssh_key>
```

Execution loop:
1. Copy harness source to target
2. Compile on target
3. For each timing value in range:
   - Run harness N times
   - Capture stdout + dmesg
   - Check for KASAN reports
4. Collect all results
5. Run verdict matcher
6. Emit verdict.json with timing metadata

This is where the Z3 witness plan becomes genuinely useful: it tells us which thread needs to go first and where the race window is. The timing sweep systematically explores that window instead of relying on random scheduling.

### 3.4 Verdict aggregator

New module: `mock/verdict/aggregate.py`

When running a harness with timing sweep, aggregate results across all runs:

```json
{
    "candidate_id": "cand_1a2b3c4d",
    "verdict": "TIMING_INCONCLUSIVE",
    "runs_total": 600,
    "runs_by_timing": {
        "0us": {"runs": 100, "crashes": 0, "setup_failures": 0},
        "100us": {"runs": 100, "crashes": 0, "setup_failures": 2},
        "1000us": {"runs": 100, "crashes": 1, "setup_matched": 1},
        ...
    },
    "best_timing_us": 1000,
    "crash_rate_at_best": 0.01,
    "timing_sensitivity": "high"
}
```

### Verification
- Generate harness for sample candidate, compile on macOS (native, not arm64 — just check it compiles)
- Cross-compile for arm64 if toolchain available
- Unit test: harness generator produces valid C for each template
- Unit test: timing sweep executor handles all verdict states

### Done when
- Harness generator covers all 6 manually-mapped KVM entry functions
- Timing sweep produces aggregate verdict
- Full pipeline: candidate -> harness -> execute -> verdict runs end-to-end against a target

---

## Phase 4: Orchestrator

**Goal:** One command that takes a candidate and produces a verdict.

### 4.1 Top-level verifier command

New script: `scripts/verify_candidate.sh` (repo root)

```bash
./scripts/verify_candidate.sh \
    --candidate uaf-bridge/out/uafx_kvm_candidate.json \
    --target-host <user@host> \
    --ssh-key <key> \
    --strategy harness          # or: witness, fuzz, all
    --timeout 600
```

Strategy modes:
- `harness`: generate C harness, timing sweep, verdict (fastest, most focused)
- `witness`: generate syz witness, execute via syz-executor, verdict
- `fuzz`: current seeded fuzzing mode with verdict matcher added
- `all`: try harness first, fall back to witness, fall back to fuzz

### 4.2 Candidate batch runner

New script: `scripts/verify_batch.sh`

```bash
./scripts/verify_batch.sh \
    --candidates-dir uaf-bridge/out/candidates/ \
    --target-host <user@host> \
    --ssh-key <key> \
    --timeout-per-candidate 300
```

Runs verify_candidate.sh for each candidate, collects verdicts into:
```
verdicts/
├── cand_1a2b3c4d/
│   ├── candidate.json
│   ├── witness_plan.json
│   ├── witness.syz
│   ├── harness.c
│   └── verdict.json
├── cand_5e6f7g8h/
│   └── ...
└── summary.json      # aggregate: N confirmed, M refuted, K inconclusive
```

### 4.3 Local-only mode (no target)

For development and testing on macOS without a Linux target:

```bash
./scripts/verify_candidate.sh \
    --candidate candidate.json \
    --local-only
```

This runs everything except actual execution:
- Generates witness.syz and validates it
- Generates harness.c and compiles it (native, checks syntax)
- Produces a "pending" verdict with all artifacts ready for execution
- Useful for testing the pipeline without a target machine

---

## Execution Model Summary

```
macOS (local)                          Linux target (remote)
─────────────                          ─────────────────────
candidate.json
    │
    ▼
Z3 solve → witness_plan.json
    │
    ├─► emit witness.syz
    │   validate locally
    │       │
    │       └──── SCP ────────────►    syz-executor runs witness
    │                                      │
    │                                      ▼
    │                              dmesg + KASAN output
    │                                      │
    │       ◄──── SCP ────────────┘
    │
    ├─► generate harness.c
    │   validate locally
    │       │
    │       └──── SCP ────────────►    gcc + run with timing sweep
    │                                      │
    │                                      ▼
    │                              stdout + dmesg + KASAN
    │                                      │
    │       ◄──── SCP ────────────┘
    │
    ▼
crash_parser + crash_matcher
    │
    ▼
verdict.json
```

All intelligence (generation, validation, verdict judgment) runs on macOS.
The Linux target is a dumb execution endpoint: receive binary, run it, return output.

---

## Phase Dependencies

```
Phase 0: enforce bridge intent in MOCK mutation
    │
    ▼
Phase 1: verdict layer (crash parser + matcher + verdict emitter)
    │
    ├──► Phase 2: runnable witness layer (syz description harvester + emitter + executor)
    │
    └──► Phase 3: micro-harness layer (C generator + cross-compile + timing sweep)
              │
              ▼
         Phase 4: orchestrator (single-command verifier + batch runner)
```

Phase 1 is required before anything else — without verdicts, nothing is measurable.
Phases 2 and 3 can proceed in parallel after Phase 1.
Phase 4 ties them together.

---

## File Layout (new files only)

```
madelin/
├── scripts/
│   ├── verify_candidate.sh          # Phase 4: top-level verifier
│   └── verify_batch.sh              # Phase 4: batch runner
├── uaf-bridge/
│   ├── harness/
│   │   ├── __init__.py
│   │   ├── generate_harness.py      # Phase 3: C harness generator
│   │   └── kvm_templates.py         # Phase 3: KVM-specific C fragments
│   ├── mapping/
│   │   └── syz_descriptions.py      # Phase 2: syz description parser
│   └── runtime/
│       ├── emit_witness_syz.py      # Phase 2: REPLACE existing file
│       └── validate_witness.py      # Phase 2: local witness validator
└── mock/
    ├── verdict/
    │   ├── __init__.py
    │   ├── parse_crash.py           # Phase 1: KASAN parser
    │   ├── match_candidate.py       # Phase 1: crash-to-candidate matcher
    │   ├── emit_verdict.py          # Phase 1: verdict.json emitter
    │   └── aggregate.py             # Phase 3: timing sweep aggregator
    └── scripts/
        ├── run_witness.sh           # Phase 2: witness executor
        ├── run_harness.sh           # Phase 3: harness executor
        └── build_harness.sh         # Phase 3: cross-compile helper
```

Total new code estimate:
- Phase 0: ~100 lines Rust (mutation guards)
- Phase 1: ~500 lines Python (parser + matcher + emitter + tests)
- Phase 2: ~800 lines Python + ~100 lines bash (description parser + witness emitter + validator + executor)
- Phase 3: ~700 lines Python + ~200 lines bash (harness generator + templates + executor + aggregator)
- Phase 4: ~200 lines bash (orchestrator scripts)

Total: ~2,600 lines of new code. Compact.

---

## Verdict Taxonomy (canonical, used across all phases)

| Verdict | Meaning | Required evidence |
|---------|---------|-------------------|
| CONFIRMED | KASAN UAF at predicted location | crash_type=UAF AND loc0 in free_stack AND loc1 in crash_stack |
| REACHED_NO_CRASH | Predicted paths exercised, no UAF | execution log shows entry functions called, K runs, no matching crash |
| UNRELATED_CRASH | Crash but wrong location/type | crash occurred but stack doesn't match loc0/loc1 |
| SETUP_FAILED | KVM resource chain broke | setup calls returned errors (ENODEV, EINVAL, fd<0) |
| TIMING_INCONCLUSIVE | Race window entered but not hit | both threads reached target functions, no crash after K timing variations |
| PATH_INFEASIBLE | Entry path unreachable at runtime | entry function never appears in execution trace after multiple attempts |

Every execution of every strategy (witness, harness, fuzz) must terminate in one of these states.

---

## Evaluation Plan

### Phase 1 evaluation (verdict layer only)
- Collect 10 real KASAN UAF reports from kernel mailing list / syzbot
- Construct synthetic candidate.json files matching 5 of them, not matching the other 5
- Run verdict matcher: expect 5 CONFIRMED, 5 UNRELATED_CRASH
- Measure: false positive rate, false negative rate

### Phase 2 evaluation (runnable witness)
- Generate witnesses for all candidates currently produced by the bridge demo
- Validate 100% pass local validation
- Execute against a test target
- Compare: time-to-verdict vs current seeded fuzzing

### Phase 3 evaluation (micro-harness)
- Select 5 known-real KVM UAFs from kernel git history (CVEs with patches)
- Construct candidates from the patch context
- Generate harnesses
- Run timing sweep
- Measure: confirmation rate, time to first crash, optimal timing value

### Cross-strategy evaluation
- Run all 3 strategies (harness, witness, fuzz) on same candidates
- Compare:
  - Time to verdict
  - Verdict accuracy
  - Coverage of candidate code region
  - Resource cost (CPU-seconds, memory)

### Regression test
- After each phase, re-run bridge tests + MOCK tests
- Verify no architecture boundary violations
- Verify existing seeded fuzzing still works unchanged

---

## What this plan does NOT do

- Does not replace general fuzzing (that remains available as a fallback strategy)
- Does not require full KVM semantic modeling (harnesses use real syscalls, not simulated ones)
- Does not require local VMs on macOS (all execution is remote)
- Does not change the UAFX layer (it already produces sufficient structural evidence)
- Does not require a database or web service (all state is files on disk)
- Does not try to synthesize arbitrary argument values (uses syzkaller descriptions or known-good defaults)

## What this plan does

- Closes the loop: candidate -> execution -> verdict
- Makes every improvement measurable against verdict rate
- Keeps the system compact (~2,600 new lines total)
- Runs on macOS with SSH to a Linux target
- Preserves the three-layer architecture
- Produces artifacts that are debuggable and auditable (all JSON + C + syz on disk)
