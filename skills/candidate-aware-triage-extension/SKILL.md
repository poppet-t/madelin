---
name: candidate-aware-triage-extension
description: Extend triage matching to new packs while keeping verdict semantics and evidence reporting conservative.
---

# candidate-aware-triage-extension

## Use this when
- extending focus-frame/focus-file matching to new subsystems
- adding pack-specific crash parsing/matching heuristics
- changing triage report emission or verdict logic

## Read first
- `AGENTS.md`
- `context/invariants.md`
- `backend/syz-guided/schemas/triage_report_v1.schema.json`
- `plans/schema-impact.md` (required if report fields/meaning might change)

## Steps
1. Add pack-specific focus hints as additive metadata (avoid breaking schema).
2. Keep matching explainable: evidence fields must show why a match occurred.
3. Add synthetic crash fixtures per pack and unit tests for match scores/verdicts.
4. Ensure "unrelated" vs "insufficient_data" remains meaningful.

## Guardrails
- do not claim exploitability; triage is classification, not proof
- keep verdict mapping stable unless explicitly approved and tested

