---
name: mapper-maintainer
description: Maintain entry classification and syscall-template mapping conservatively, with explicit supported and unsupported behavior.
---

# mapper-maintainer

## Use this when
- editing `uaf-bridge/mapping/`
- changing entry classification
- updating manual driver maps
- updating syscall template fragments

## Read first
- `AGENTS.md`
- `context/architecture.md`
- `context/invariants.md`
- `plans/current.md`

## Steps
1. Identify the mapping or classification boundary touched.
2. Confirm what evidence drives the mapping.
3. Implement the smallest correct change.
4. State supported and unsupported cases clearly.
5. Update stage-specific validation if needed.

## Output
- summary
- changed files
- classification or mapping impact
- validation run
- risks / assumptions

## Guardrails
- stay conservative when evidence is weak
- prefer explicit unsupported cases over broad guesses
- do not blur mapping logic into extraction or solver logic

