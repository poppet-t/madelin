---
name: repo-cartographer
description: Map the relevant codepath, boundaries, and affected files for a maintenance task before implementation begins.
---

# repo-cartographer

## Use this when
- starting work in an unfamiliar area
- the request spans multiple directories
- the user asks where a change should be made
- you need a producer -> consumer boundary map

## Read first
- `AGENTS.md`
- `context/overview.md`
- `context/architecture.md`
- `context/invariants.md`

## Steps
1. Identify the narrowest directories and files relevant to the request.
2. Trace producer -> consumer boundaries.
3. Record likely validation points.
4. Write `plans/repo-map.md`.

## Output
- relevant files
- boundary map
- likely validation commands
- risks of touching the wrong stage

## Guardrails
- do not edit code
- do not invent support beyond what the repo currently implements
- prefer a narrow map over a broad repo summary

