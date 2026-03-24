---
name: extractor-maintainer
description: Maintain the warning-to-candidate extraction and normalization layer while preserving provenance and candidate contract stability.
---

# extractor-maintainer

## Use this when
- editing `uaf-bridge/extractor/`
- changing warning import logic
- changing candidate normalization
- adjusting provenance handling

## Read first
- `AGENTS.md`
- `context/architecture.md`
- `context/invariants.md`
- `plans/current.md`

## Steps
1. Locate the exact extraction path involved.
2. Identify candidate fields produced or affected.
3. Make the smallest correct change.
4. Note any candidate schema impact.
5. Update validation or smoke coverage if needed.

## Output
- summary of extraction change
- changed files
- affected candidate fields
- validation run
- risks / assumptions

## Guardrails
- preserve provenance
- do not silently change candidate schema shape
- keep extractor responsibilities separate from solver/runtime logic

