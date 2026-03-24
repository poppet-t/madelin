---
name: schema-change-check
description: Use when a change may affect candidate.json, witness_plan.json, or downstream artifact consumers.
---

# schema-change-check

## Purpose
Prevent accidental schema drift across bridge stages.

## Use this when
- Adding fields
- Renaming fields
- Reinterpreting field meaning
- Changing ordering semantics encoded in artifacts
- Updating validators or typed consumers

## Required reads
- `AGENTS.md`
- `context/invariants.md`
- schema files
- producer code
- consumer code
- relevant smoke scripts

## Procedure
1. List every producer of the touched artifact.
2. List every consumer of the touched artifact.
3. Identify whether the change is:
   - additive backward-compatible
   - additive but requires downstream handling
   - breaking
4. Update all affected validations.
5. Document the impact in the final summary.

## Refusal rule
If the requested task would create silent schema drift, stop and report that explicitly.
