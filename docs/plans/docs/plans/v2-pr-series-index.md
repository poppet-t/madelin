# V2 PR Series Index

This file breaks the canonical verifier architecture plan at `docs/plans/docs/plans/v2-verifier-architecture.md` into the first 5 implementation PRs.

## Goal
Turn the current bridge-guided seeded fuzzing workflow into a candidate-specific verification workflow with:
- measurable verdicts
- runnable witness execution
- candidate-specific micro-harness execution
- a simple top-level verifier command

## Sequence

### PR1 — Foundation enforcement + verdict layer skeleton
Focus:
- enforce existing bridge intent in MOCK mutation
- add verdict package skeleton
- add crash parser + matcher + verdict emitter
- do not add runnable witness or harness execution yet

Primary outputs:
- `mock/verdict/*`
- mutation guards for prefix/order preservation
- `verdict.json` generation from existing fuzz outputs

### PR2 — Runnable witness foundation
Focus:
- replace pseudo witness with real runnable witness emitter
- add local witness validator
- keep execution path minimal and SSH-based

Primary outputs:
- real `witness.syz`
- witness validation tooling

### PR3 — Witness remote execution + verdict integration
Focus:
- add `run_witness.sh`
- copy witness and executor to Linux target
- run witness remotely
- emit `verdict.json`

Primary outputs:
- candidate-specific witness execution path

### PR4 — Micro-harness foundation
Focus:
- add harness generator for narrow KVM candidate subset
- compile/execute remotely over SSH
- add timing sweep and aggregate verdicts

Primary outputs:
- per-candidate `harness.c`
- timing-sensitive verification path

### PR5 — Orchestrator + unified verification flow
Focus:
- add top-level `verify_candidate.sh`
- add `verify_batch.sh`
- unify `fuzz`, `witness`, and `harness` strategies
- produce stable per-candidate artifact directories

Primary outputs:
- one-command verifier workflow
- batch evaluation support

## Rules for the PR series
- Preserve the 3-layer architecture in `CLAUDE.md`
- Do not move raw static-analysis logic into unrelated MOCK runtime code
- Prefer measurable improvements over architectural aesthetics
- Every PR must leave behind tests or validation commands
- Every PR must clearly state what remains heuristic

## Done criteria for the 5-PR slice
- Existing seeded fuzzing still works
- `verdict.json` exists for fuzz and witness flows
- one runnable witness path exists
- one micro-harness path exists
- top-level verification command exists
