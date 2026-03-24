# PR5 — Orchestrator and Batch Verification Flow

## Goal
Add a top-level verification command and batch runner that unify `fuzz`, `witness`, and `harness` strategies.

## Why now
After PR1–PR4, the pieces exist but the operator experience is still fragmented. This PR turns the verifier into a usable workflow.

## Current bottleneck
There is no single entry point for candidate verification and no stable batch execution layout.

## Scope
Included:
- add `scripts/verify_candidate.sh`
- add `scripts/verify_batch.sh`
- support strategy modes:
  - `harness`
  - `witness`
  - `fuzz`
  - `all`
- create stable per-candidate artifact directories
- emit batch summary

Excluded:
- dashboard/UI
- database-backed result storage
- distributed orchestration

## Assumptions
- PR1–PR4 provide the underlying execution modes
- shell-based orchestration is sufficient for the first unified operator workflow

## Impacted files/modules
- `scripts/verify_candidate.sh`
- `scripts/verify_batch.sh`
- maybe small supporting helper scripts
- docs/README updates

## Risks
- strategy dispatch may become messy if earlier PR interfaces are inconsistent
- batch summary may need to tolerate partial failures
- artifact directory conventions need to be stable

## Implementation order
1. Define CLI contract
2. Define artifact directory layout
3. Implement single-candidate orchestration
4. Implement batch runner
5. Add summary generation
6. Update docs/tests

## Verification plan
- shell syntax checks
- local dry-run mode if available
- one candidate per strategy
- small multi-candidate batch smoke test

## Rollback / fallback notes
- orchestration must call existing modes, not reimplement them
- failures should be explicit and candidate-scoped

## Definition of done
- one command can verify a candidate with a chosen strategy
- one command can verify a batch of candidates
- artifacts and summaries are saved deterministically

## Exact next step for Codex
Implement PR5 only, assuming PR1–PR4 are already merged.

## Allowed edit scope
- `scripts/*`
- narrowly needed helper docs/tests
- minimal supporting glue

## Must remain unchanged
- underlying PR1–PR4 execution semantics
- 3-layer architectural separation