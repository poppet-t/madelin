# PR2 — Runnable Witness Foundation

## Goal
Replace the current pseudo witness output with a real runnable witness representation and add a local validator.

## Why now
The bridge currently emits a comment-style witness that is descriptive but not executable.
A verifier needs a candidate-specific runtime artifact that can actually be executed.

## Current bottleneck
`witness.syz` is not runnable and is not consumed downstream.

## Scope
Included:
- replace `uaf-bridge/runtime/emit_witness_syz.py` behavior with real syz-style witness emission
- add `uaf-bridge/runtime/validate_witness.py`
- add `uaf-bridge/mapping/syz_descriptions.py` or a narrower equivalent for the initial KVM subset
- support the narrow KVM/arm64 syscall set already present in templates

Excluded:
- remote witness execution
- verdict wiring for witness execution
- micro-harness generation
- broad subsystem generalization

## Assumptions
- initial witness generation can focus on the narrow KVM arm64 template subset already used by the bridge
- syzkaller descriptions available in-repo or via existing patched tree are sufficient for initial argument shape extraction
- initial witness programs can still use conservative known-good defaults for some structs

## Impacted files/modules
- `uaf-bridge/runtime/emit_witness_syz.py`
- `uaf-bridge/runtime/validate_witness.py`
- `uaf-bridge/mapping/syz_descriptions.py`
- relevant tests under `uaf-bridge/tests/`
- possibly `uaf-bridge/README.md`

## Risks
- syz format correctness may be trickier than expected
- struct/value defaults may be underconstrained
- real ioctl number/argument extraction may need a narrower scope than planned

## Implementation order
1. Define the minimal supported KVM witness subset
2. Add description harvesting/parsing for that subset
3. Replace comment-block witness emission with runnable witness emission
4. Add local validator
5. Add tests using sample candidate/plan pairs

## Verification plan
- `cd uaf-bridge && ./.venv_ci/bin/python -m pytest -q`
- run bridge demo and inspect emitted `witness.syz`
- run local validator on emitted witness
- compare output shape against real syz syntax expectations

## Rollback / fallback notes
- if full runnable emission for all current templates is too large, support only a narrow verified KVM subset and fail explicitly for unsupported shapes
- do not reintroduce comment-only witness output silently

## Definition of done
- emitted `witness.syz` is intended to be runnable, not comment-only
- local witness validator exists and passes on supported samples
- unsupported witness shapes fail explicitly with clear messages

## Exact next step for Codex
Implement PR2 only, assuming PR1 is already merged.

## Allowed edit scope
- `uaf-bridge/runtime/*`
- `uaf-bridge/mapping/*`
- `uaf-bridge/tests/*`
- `uaf-bridge/README.md`

## Must remain unchanged
- candidate and plan semantics unless strictly needed
- separation between bridge emission and runtime execution