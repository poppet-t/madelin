---
name: runtime-emitter-maintainer
description: Maintain witness and pseudo-syzkaller emission while preserving ordering, determinism, and stage boundaries.
---

# runtime-emitter-maintainer

## Use this when
- editing `uaf-bridge/runtime/`
- changing witness emission
- changing pseudo-syzkaller generation
- changing ordering preservation in emitted outputs

## Read first
- `AGENTS.md`
- `context/architecture.md`
- `context/invariants.md`
- `plans/current.md`

## Steps
1. Identify the exact runtime emission boundary touched.
2. Confirm what witness-plan fields are consumed.
3. Make the smallest correct change.
4. Check ordering preservation and deterministic output.
5. Update validation if needed.

## Output
- summary
- changed files
- emitted artifact impact
- validation run
- risks / assumptions

## Guardrails
- preserve deterministic emission for identical inputs
- do not move dynamic healing into earlier bridge stages
- do not silently reinterpret witness-plan semantics

