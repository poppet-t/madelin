---
name: solver-maintainer
description: Maintain SMT encoding and witness extraction while preserving structural-feasibility semantics and stock Z3 usage.
---

# solver-maintainer

## Use this when
- editing `uaf-bridge/smt/`
- changing ordering constraints
- changing alias/resource predicates
- changing witness extraction from SAT models

## Read first
- `AGENTS.md`
- `context/architecture.md`
- `context/invariants.md`
- `plans/current.md`

## Steps
1. Identify the exact constraint family or extraction path touched.
2. Determine whether candidate or witness fields are affected.
3. Implement the smallest correct solver change.
4. Keep the change focused on structural feasibility.
5. Update or add targeted validation.

## Output
- summary
- changed files
- constraint impact
- validation run
- risks / assumptions

## Guardrails
- use stock Z3 behavior
- avoid speculative semantic modeling
- do not silently change witness-plan shape

