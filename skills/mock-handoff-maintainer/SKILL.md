---
name: mock-handoff-maintainer
description: Maintain the bridge-to-MOCK import path, including seed import, relations, and bias generation, without hidden coupling.
---

# mock-handoff-maintainer

## Use this when
- editing `mock/tools/import_bridge_seed.py`
- changing relations or bias generation
- changing seed import behavior
- changing KVM seed preparation scripts

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
- keep the bridge and MOCK connected by explicit artifacts, not hidden coupling
- preserve stable prefix intent where applicable
- fail clearly on unsupported imported shapes

