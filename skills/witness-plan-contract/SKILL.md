---
name: witness-plan-contract
description: Preserve and extend witness_plan.json generation with deterministic ordering and explicit unsupported cases.
---

# witness-plan-contract

## Use this when
- changing SMT encoding, solve, or witness-plan extraction
- adding lifecycle edges or pack-specific scheduling hints
- changing witness emission/validation assumptions

## Read first
- `AGENTS.md`
- `context/invariants.md`
- `uaf-bridge/schemas/witness_plan.schema.json`
- `plans/schema-impact.md` (required if semantics/order might change)

## Steps
1. Identify the exact producer(s) and consumer(s) of witness plans.
2. Confirm ordering semantics and determinism requirements.
3. Add pack-specific hints as additive metadata; avoid reinterpretation of existing fields.
4. Ensure unsupported shapes fail with explicit, typed reasons.
5. Add unit tests that pin determinism on fixtures.

## Guardrails
- do not silently change ordering semantics
- do not backfill semantic argument synthesis claims
- keep plan validity checkable from artifacts alone

