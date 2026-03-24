# Feature Plan: kvm-refinement-pass-1

## Goal
Determine the current weakest link in the arm64 KVM bug-hunting pipeline and improve the highest-value structural bottleneck with a bounded follow-up patch.

## Why
The repo now has an end-to-end architecture:
- UAFX finds candidates
- bridge exports seed intent
- MOCK imports seed intent and biases fuzzing

The immediate question is no longer “can the system run?”
It is:
- where is the current bug-finding quality bottleneck?

We need to decide whether the next best step is:
- KVM mapping expansion
- seed-quality refinement
- bridge-bias refinement
- or better experiment/debug tooling

## Scope
Included:
- inspect current outputs and testing loops
- identify the current weakest link
- propose the next bounded implementation step
- define how success will be measured

Not included:
- broad architecture redesign
- large semantic KVM modeling work
- rewriting multiple subsystems at once

## Assumptions
- The current bridge pipeline runs end-to-end.
- `mock_seed.json` generation works.
- MOCK importer and seeded workflows exist.
- The current system is still mostly structural, not semantically complete.
- arm64 KVM remains the primary target.

## Constraints
- Preserve UAFX -> bridge -> MOCK separation.
- Prefer bounded changes in one layer at a time.
- Do not claim improved bug finding without comparison-oriented validation.
- Keep grounded vs heuristic distinctions clear.

## Impacted areas
Likely review targets:
- `uaf-bridge/mapping/syscall_templates.py`
- `uaf-bridge/runtime/export_mock_seed.py`
- `mock/bridge_seed/corpus.py`
- `mock/bridge_seed/policy.py`
- `mock/healer_core/src/bridge_bias.rs`
- `mock/tools/corpus_histogram.py`
- relevant tests under `uaf-bridge/tests/` and `mock/tests/`

## Risks
- improving artifact quality without improving real fuzzing focus
- overfitting to pretty KVM seeds that do not survive runtime
- making MOCK too dependent on bridge-only structure
- adding more heuristics without measuring whether they help

## Inspection results (2026-03-19)

### Bridge output quality
The bridge produces well-structured, deterministic artifacts:
- `candidate.json`: schema-validated, 6 default events, 2 grounded KVM entries
- `witness_plan.json`: SAT with 2-thread schedule, soft constraint satisfied
- `mock_seed.json`: 3-call setup, 6-call trigger, 10 focus families, explicit resource deps

Bridge strengths:
- Structural schema and validation are solid
- Grounded entry mapping (narrow slice of 6 KVM functions) is correct
- Partial-order preservation works (escape→fetch, free→use)
- Seed intent clearly separates setup, trigger, predicates, mutation guidance

Bridge weaknesses (lower priority):
- Only ~10 of 100+ KVM ioctls have templates
- Arguments are all placeholders (`&init`, `&one_reg`) — no real values
- Predicates are tracked but never enforced in Z3
- Manual entry map covers only 6 KVM functions

### MOCK consumption of bridge intent
This is where the pipeline breaks down. MOCK integration scorecard:

| Bridge field              | Defined | Consumed by fuzzer | Enforced |
|---------------------------|---------|-------------------|----------|
| focus_syscall_families    | Yes     | Yes               | Yes      |
| seed programs (corpus)    | Yes     | Yes               | Yes      |
| relation edges            | Yes     | Yes               | Yes      |
| preserve_prefix_len       | Yes     | **No**            | **No**   |
| keep_ordering_edges       | Yes     | **No**            | **No**   |
| stable_prefix_resources   | Yes     | **No**            | **No**   |
| mutate_near_steps         | Yes     | **No**            | **No**   |
| prefer_collide            | Yes     | **No**            | **No**   |
| prefer_two_thread_schedule| Yes     | Partial           | Partial  |
| abstract_step mapping     | Yes     | **No**            | **No**   |

**MOCK consumes roughly 30% of the bridge's structural intent.**

### Concrete impact of the gap
A seeded program like:
```
openat$KVM(...)              # idx 0 - setup
ioctl$KVM_CREATE_VM(...)     # idx 1 - setup
ioctl$KVM_CREATE_VCPU(...)   # idx 2 - setup
ioctl$KVM_ARM_VCPU_INIT(...) # idx 3 - trigger
ioctl$KVM_SET_ONE_REG(...)   # idx 4 - trigger
ioctl$KVM_RUN(...)           # idx 5 - trigger
```
The bridge says: keep indices 0-2 intact, preserve escape→fetch→use ordering, focus mutations near fetch/use.

What the fuzzer actually does: uniform random mutation across all calls, including removing setup calls and reordering causality. Result: many mutants have broken setup chains or violated ordering — wasted test cases that never reach the bug-triggering window.

---

## Current weakest link

**MOCK's mutation logic ignores the bridge's structural constraints.**

The bridge emits `preserve_prefix_len`, `keep_ordering_edges`, and `mutate_near_steps` specifically to protect the KVM setup chain and concentrate mutations on the race window. None of these are enforced during mutation. This is the single highest-leverage gap because:

1. It wastes cycles on structurally broken test cases
2. It negates the value of bridge-guided seeding
3. It is bounded to MOCK-layer changes only (no bridge or UAFX changes needed)
4. It does not require semantic KVM knowledge — just respecting existing metadata

---

## Best next bounded patch

**Enforce `preserve_prefix_len` in MOCK's mutation logic.**

This is the narrowest, highest-value fix:
- The bridge already emits `preserve_prefix_len: 3` in every seed
- `bridge_bias.rs` already loads the bias JSON but ignores this field
- Mutation functions in `healer_core/src/mutation/` can remove, splice, or reorder any call including the protected setup prefix
- The fix: make the mutator treat the first N calls as immutable during `remove_call()`, `splice()`, and `insert_calls()` operations

Why this before ordering edges:
- Prefix preservation is simpler to implement (index range check vs graph constraint)
- It protects the most critical invariant (valid KVM fd chain)
- It is independently valuable even without ordering enforcement
- Ordering edges can be the follow-up patch

---

## Files to edit

Primary (implementation):
- `mock/healer_core/src/bridge_bias.rs` — expose `preserve_prefix_len` from loaded bias
- `mock/healer_core/src/mutation/seq.rs` — skip prefix indices during remove/splice/reorder
- `mock/healer_core/src/mutation/arg.rs` — allow arg mutation within prefix (only structural changes are blocked)

Secondary (validation):
- `mock/bridge_seed/policy.py` — verify `preserve_prefix_len` is always emitted
- `mock/tests/test_bridge_seed.py` — add test that prefix calls survive mutation round-trip

Do not touch:
- `uaf-bridge/` — no changes needed; it already emits the field
- `mock/bridge_seed/corpus.py` — corpus generation is fine; the problem is post-import mutation

---

## Shortest validation loop

1. **Unit**: `cd mock && cargo test -p healer_core` — verify mutation functions respect prefix bound
2. **Artifact**: `cd mock && bash scripts/prepare_kvm_seed.sh` — regenerate seed workdir
3. **Inspection**: Manually verify that after N mutation rounds, prefix calls (openat, CREATE_VM, CREATE_VCPU) remain intact and in order
4. **Histogram**: `cd mock && python3 tools/corpus_histogram.py ./seed_workdir/input` — confirm KVM setup calls appear in 100% of corpus entries (currently they can be removed)
5. **Smoke** (optional): Short `--max-seconds 30` seeded run — confirm fuzzer starts and loads bias without error

Success criteria:
- All corpus programs retain the 3-call KVM setup prefix after mutation
- No regression in existing bridge/MOCK tests
- `bridge_bias.rs` exposes `preserve_prefix_len` and mutation code reads it
- Histogram shows openat$KVM + CREATE_VM + CREATE_VCPU in every generated program

---

## Implementation plan (updated)

Phase 1 — prefix preservation (this patch):
1. Extend `bridge_bias.rs` to parse and expose `preserve_prefix_len`
2. Thread the prefix length into mutation functions via context or config
3. Guard `remove_call()` and `splice()` against removing prefix-range calls
4. Guard `insert_calls()` against inserting before prefix end
5. Add Rust unit tests for prefix invariant
6. Add Python test that imported seed preserves prefix after simulated mutation

Phase 2 — ordering edge enforcement (follow-up):
- Parse `keep_ordering_edges` in `bridge_bias.rs`
- Add constraint check in mutation to prevent reordering across edges
- Separate plan file: `docs/plans/kvm-refinement-pass-2.md`

Phase 3 — mutation targeting (future):
- Map `mutate_near_steps` to call indices
- Bias mutation site selection toward those indices
- Requires abstract_step→call_index mapping in seed import

---

## Rollback plan
- Patch is bounded to MOCK mutation logic only
- If prefix enforcement causes mutation starvation (too few valid mutations), add a bypass flag `--ignore-prefix-guard` and revert to uniform mutation
- No bridge changes to revert

## Definition of done
- `preserve_prefix_len` is enforced during mutation
- KVM setup prefix survives all mutation types
- Existing tests pass
- New tests cover prefix invariant
- Histogram confirms structural improvement
- Follow-up (ordering edges) is documented as next step

## Handoff to Codex
### Exact next step
Implement `preserve_prefix_len` enforcement in MOCK's Rust mutation logic.

### Allowed edit scope
- `mock/healer_core/src/bridge_bias.rs`
- `mock/healer_core/src/mutation/seq.rs`
- `mock/healer_core/src/mutation/arg.rs`
- `mock/tests/test_bridge_seed.py`
- `mock/bridge_seed/policy.py` (validation only, no logic changes)

### Verification commands
```bash
cd mock && cargo test -p healer_core
cd mock && PYTHONPATH=. python3 -m unittest
cd mock && bash scripts/prepare_kvm_seed.sh
cd mock && python3 tools/corpus_histogram.py ./seed_workdir/input
```

### What must remain unchanged
- Bridge output format and content
- Seed import logic in `bridge_seed/corpus.py`
- Relation edge loading in `bridge_bias.rs`
- Focus syscall family weighting

### Notes
This is a MOCK-only patch. The bridge already provides the right metadata — the fuzzer just needs to respect it. Keep the implementation minimal: index range checks in mutation functions, not a new constraint-solving framework.