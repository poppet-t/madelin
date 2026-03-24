---
name: create-plan
description: Use for any non-trivial task before implementation. Produces or updates plans/current.md with the smallest safe execution path.
---

# create-plan

## Use this when
- The task affects multiple files
- The task touches architecture boundaries
- The task is not a tiny local edit
- The user asks for planning, sequencing, or implementation strategy

## Required reads
- `AGENTS.md`
- `context/overview.md`
- `context/architecture.md`
- `context/invariants.md`
- `context/current-status.md`
- `context/known-issues.md`

## Steps
1. Identify the exact task.
2. Identify relevant files only.
3. Record the hard constraints.
4. Write a minimal numbered plan in `plans/current.md`.
5. Include targeted validation steps.
6. Do not edit code unless the user explicitly asked for implementation.

## Output
Update `plans/current.md` with:
- task
- constraints
- relevant files
- plan
- validation
- done criteria
