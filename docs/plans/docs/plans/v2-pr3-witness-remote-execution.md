# PR3 — Witness Remote Execution and Verdict Integration

## Goal
Add a remote execution path for `witness.syz` and produce `verdict.json` for witness runs.

## Why now
After PR2, the system has a runnable witness artifact. It still lacks a clean path to execute that witness against a Linux target and judge the result.

## Current bottleneck
No candidate-specific witness execution mode exists. Only the broad fuzz mode executes against the target.

## Scope
Included:
- add `mock/scripts/run_witness.sh`
- copy witness and executor to remote target via SSH/SCP
- execute witness remotely
- collect output and logs
- reuse PR1 verdict layer to emit `verdict.json`

Excluded:
- micro-harness generation
- top-level orchestrator
- broad campaign management
- advanced coverage oracle

## Assumptions
- SSH-based execution is sufficient for the first witness path
- existing target setup already supports remote file transfer and execution
- initial witness executor can be simple and mostly shell-based

## Impacted files/modules
- `mock/scripts/run_witness.sh`
- possibly small helper modules under `mock/verdict/`
- maybe small updates in `uaf-bridge/runtime/` if execution metadata needs to be embedded
- tests/docs as appropriate

## Risks
- remote environment differences may affect execution reliability
- witness execution may require stricter syz-executor assumptions than expected
- log collection may be inconsistent across targets

## Implementation order
1. Define witness execution contract and inputs
2. Add remote copy + execution wrapper
3. Collect logs/crash outputs
4. Reuse verdict matcher/emitter
5. Add dry-run and minimal tests

## Verification plan
- `cd mock && bash -n scripts/run_witness.sh`
- local dry-run of SCP/SSH command assembly
- remote smoke test against a real or prepared Linux target
- emit `verdict.json` for witness run

## Rollback / fallback notes
- keep witness execution isolated from fuzz flow
- fail explicitly on unsupported target state rather than silently falling back to fuzzing

## Definition of done
- one command can execute a candidate-specific witness remotely
- witness run emits `verdict.json`
- logs/artifacts are saved predictably

## Exact next step for Codex
Implement PR3 only, assuming PR1 and PR2 are already merged.

## Allowed edit scope
- `mock/scripts/run_witness.sh`
- `mock/verdict/*`
- narrowly needed helper files
- docs/tests

## Must remain unchanged
- existing fuzz execution path
- separation between bridge artifact generation and runtime execution wrapper