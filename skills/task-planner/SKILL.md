---
name: task-planner
description: Turn a request into the smallest safe execution plan with explicit constraints, files, validation, and done criteria.
---

# task-planner

## Use this when
- the task is non-trivial
- the request spans multiple files
- the task touches architecture boundaries
- implementation should be staged
- validation needs to be planned before coding
- the user asks for planning, sequencing, or implementation strategy

## Read first
- `AGENTS.md`
- `context/*`
- `plans/repo-map.md` if present

## Steps
1. Restate the task in one paragraph.
2. List hard constraints and non-goals.
3. Name the smallest set of relevant files.
4. Write a numbered execution plan to `plans/current.md`.
5. Include the narrowest relevant validation.
6. Define clear done criteria.

## Output
Update `plans/current.md` with:
- task
- constraints
- relevant files
- plan
- validation
- done criteria

## Guardrails
- do not edit code unless explicitly asked
- prefer the smallest safe plan
- avoid architecture redesign by default

