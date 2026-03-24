---
name: witness-bridge-task
description: Use for changes to the UAFX -> candidate -> SMT -> runtime -> MOCK bridge. Enforces contract preservation, narrow diffs, and validation discipline.
---

# witness-bridge-task

## Use this when
- Editing extraction, mapping, SMT, runtime emission, or MOCK import logic
- Changing artifact boundaries
- Adding support for a narrow new entry family
- Debugging witness feasibility or scaffold generation

## Required reads
- `AGENTS.md`
- `context/architecture.md`
- `context/invariants.md`
- `plans/current.md`

## Required behavior
- Preserve artifact contracts unless explicitly authorized otherwise.
- Keep unsupported cases explicit.
- Prefer additive extension points over redesign.
- Preserve provenance and reproducibility metadata.
- Do not blur stage responsibilities.

## Checklist
Before editing, identify whether the change affects:
- candidate schema
- witness plan schema
- runtime emitter assumptions
- mock seed importer assumptions
- ordering semantics
- stable resource prefix expectations

## Execution sequence
1. Find the exact producer and consumer boundaries touched.
2. Confirm whether this is:
   - local logic change
   - schema change
   - ordering/constraint change
   - runtime-only emission change
3. Implement the smallest correct diff.
4. Add or update validation for the touched stage.
5. Run narrow checks first.
6. Report assumptions and unverified paths.

## Final output format
- Summary
- Changed files
- Boundary touched
- Validation run
- Risks / assumptions
- Follow-ups
