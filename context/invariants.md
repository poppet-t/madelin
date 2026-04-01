# Invariants

## Hard contract invariants

- `candidate.json` field meanings must not change silently.
- `witness_plan.json` field meanings must not change silently.
- Ordering semantics must not change silently.
- Runtime artifacts must reference their source artifacts.

## Scope invariants

- v1 support remains narrow and evidence-backed.
- Do not claim generalized subsystem support.
- Do not claim arbitrary schedule synthesis.
- Do not claim full symbolic execution.

## Backend invariants

- Mandatory bootstrap prefixes must remain preservable.
- Producer→consumer resource chains must be representable explicitly.
- Candidate-aware triage must remain tied to focus frames/files/free-use hints.
- Every campaign must save artifacts for reproducibility.

## Validation invariants

- Narrow smoke checks come before end-to-end runs.
- Validation evidence must be written to `plans/validation-report.md`.