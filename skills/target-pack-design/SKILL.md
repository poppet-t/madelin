---
name: target-pack-design
description: Add or extend a Madelin target pack with minimal contracts, fixtures, and conservative support claims.
---

# target-pack-design

## Use this when
- adding a new target pack under `targets/`
- extending pack metadata, lifecycle templates, or entry-kind normalization
- scoping support claims by pack maturity

## Read first
- `AGENTS.md`
- `context/overview.md`
- `context/invariants.md`
- `plans/current.md`
- `plans/schema-impact.md` (if artifacts might change)

## Steps
1. Define pack identity: name, kernel_area conventions, and target_family values.
2. Define supported entry kinds (normalized taxonomy, not semantic synthesis).
3. Define at least one fixture family for the pack (bridge export -> candidate -> witness plan).
4. Define at least one backend dry-run proof that reaches triage artifacts without special hardware.
5. Mark maturity conservatively and document unsupported cases explicitly.

## Guardrails
- do not change `candidate.json` or `witness_plan.json` semantics without schema review
- do not claim live execution support without recorded evidence
- keep KVM fixtures non-regressing while generalizing

