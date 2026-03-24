---
name: reviewer-regression
description: Review diffs for regressions, schema drift, unsafe assumptions, and missing validation, with findings only and highest severity first.
---

# reviewer-regression

## Use this when
- reviewing diffs before commit
- checking risky bridge changes
- evaluating runtime or importer changes
- looking for hidden assumptions in orchestration or shell scripts

## Read first
- `AGENTS.md`
- `plans/current.md`
- `plans/schema-impact.md` if present
- `plans/validation-report.md` if present
- changed files and diff

## Review priorities
1. correctness
2. regressions
3. schema drift
4. unsafe assumptions
5. missing validation
6. maintainability risks

## What to flag
- silent contract changes
- producer/consumer mismatch
- lost ordering semantics across stages
- support broadened without tests
- environment-sensitive behavior hidden as if general
- shell script duplication that increases drift risk

## Output
- findings only
- highest severity first
- exact files and reasoning
- no praise padding

## Guardrails
- do not rewrite code during review
- do not dilute serious issues with style commentary
- prefer concrete evidence over speculative criticism

