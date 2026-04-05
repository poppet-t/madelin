---
name: subsystem-fixture-generation
description: Create conservative fixtures for new subsystem packs without inventing semantics or widening support claims.
---

# subsystem-fixture-generation

## Use this when
- adding fixture raw warnings or bridge-export fixtures for new packs (io_uring/net/bpf/fs)
- scaffolding new candidate families for end-to-end dry-run proof

## Read first
- `AGENTS.md`
- `context/invariants.md`
- `plans/repo-map.md`
- `plans/schema-impact.md` (if fixture shape changes impact importers)

## Steps
1. Choose one minimal family with a clear lifecycle edge (create/register/use/teardown).
2. Create a raw-warning fixture that preserves provenance and leaves unknown fields empty.
3. Create a bridge-export fixture that sets `kernel_area`, `subsystem`, `target_family`, and entry kind hints.
4. Ensure the fixture imports deterministically into a valid `candidate.json`.
5. Add a witness-plan fixture/proof that is explicit about unsupported template families.

## Guardrails
- do not fabricate grounded kernel facts (frames/files/functions) without evidence
- prefer template-backed fixtures with explicit "heuristic" markers over fake precision

