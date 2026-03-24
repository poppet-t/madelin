---
name: status-curator
description: Update durable project memory after work completes, including current status, known issues, and plan archive notes.
---

# status-curator

## Use this when
- a task is complete
- a session is ending
- handoff notes should be recorded
- durable project memory should be updated

## Read first
- changed files
- `plans/current.md`
- `plans/validation-report.md` if present
- `plans/schema-impact.md` if present
- review findings if present
- `context/current-status.md`
- `context/known-issues.md`

## Steps
1. Update `context/current-status.md` with what is now true.
2. Update `context/known-issues.md` with any new risks or unresolved issues.
3. Optionally archive or summarize the plan in `plans/archive/`.
4. Keep updates concise and factual.

## Output
- current status updates
- known issues updates
- optional archived summary

## Guardrails
- write only what is supported by the completed work
- keep durable memory factual, not aspirational
- do not erase unresolved risks just because a code diff landed

