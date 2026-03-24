# PR4 — Micro-Harness Foundation

## Goal
Generate and execute a candidate-specific C micro-harness for a narrow KVM subset, with timing sweep and aggregate verdicts.

## Why now
This is the core verifier path:
a deterministic, focused execution strategy that directly tests a candidate hypothesis rather than relying on mutation.

## Current bottleneck
The system still depends on syz-style execution or broad fuzzing. There is no purpose-built harness per candidate.

## Scope
Included:
- add `uaf-bridge/harness/generate_harness.py`
- add `uaf-bridge/harness/kvm_templates.py`
- add `mock/scripts/build_harness.sh`
- add `mock/scripts/run_harness.sh`
- add timing sweep support
- add `mock/verdict/aggregate.py`
- support one narrow KVM candidate family first

Excluded:
- full generalization across all KVM entry families
- batch orchestration
- sophisticated runtime instrumentation beyond logs/crash outputs

## Assumptions
- a narrow candidate family is enough for the first serious verifier slice
- compilation may happen remotely if host cross-compilation is inconvenient
- timing variation can be coarse-grained initially

## Impacted files/modules
- `uaf-bridge/harness/*`
- `mock/scripts/build_harness.sh`
- `mock/scripts/run_harness.sh`
- `mock/verdict/aggregate.py`
- tests/docs as needed

## Risks
- generating valid C for all candidate shapes is too broad for one PR
- timing sweep may need target-specific tuning
- setup defaults may be fragile

## Implementation order
1. Define the first supported candidate family
2. Add KVM harness templates
3. Generate compilable `harness.c`
4. Add remote compile/execute path
5. Add timing sweep
6. Add aggregated verdict output
7. Add tests

## Verification plan
- generate harness for sample candidate and inspect output
- compile locally for syntax when possible
- compile remotely on Linux target
- run timing sweep against target
- emit aggregate `verdict.json`

## Rollback / fallback notes
- if remote compilation is the only reliable path, document it explicitly
- unsupported candidate shapes must fail explicitly
- keep the harness path isolated from witness/fuzz paths

## Definition of done
- one narrow candidate family can be turned into `harness.c`
- harness can be compiled and executed remotely
- timing sweep produces an aggregate verdict

## Exact next step for Codex
Implement PR4 only, assuming PR1–PR3 are already merged.

## Allowed edit scope
- `uaf-bridge/harness/*`
- `mock/scripts/build_harness.sh`
- `mock/scripts/run_harness.sh`
- `mock/verdict/aggregate.py`
- docs/tests

## Must remain unchanged
- existing fuzz and witness paths
- 3-layer architecture boundaries