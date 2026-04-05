---
name: mock-handoff-maintainer
description: Archived. The legacy mock/ runtime path was removed; do not use for new work.
---

# mock-handoff-maintainer (archived)

This skill is kept only as historical reference. The `mock/` directory has been removed and
`backend/syz-guided/` is the runtime consumer.

## Use this when
- you are auditing historical context or old writeups that reference `mock/`

## Read first
- `AGENTS.md`
- `context/architecture.md`
- `context/invariants.md`
- `plans/current.md`

## Steps
1. Identify the exact imported artifact and consumer path.
2. Confirm stable prefix and ordering assumptions.
3. Make the smallest correct importer or handoff change.
4. State downstream assumptions explicitly.
5. Update validation if needed.

## Output
- summary
- changed files
- downstream assumption list
- validation run
- risks / assumptions

## Guardrails
- keep runtime consumers connected by explicit artifacts, not hidden coupling
- preserve stable prefix intent where applicable
- fail clearly on unsupported imported shapes
