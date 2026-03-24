---
name: code-review-security
description: Use for review passes focused on correctness, regressions, schema drift, security assumptions, and unsafe broadening of support.
---

# code-review-security

## Use this when
- Reviewing diffs before commit
- Checking high-risk bridge changes
- Evaluating changes that touch runtime or import logic
- Looking for hidden assumptions in shell or orchestration scripts

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
- ordering semantics lost across stages
- narrow support being broadened without tests
- environment-sensitive behavior hidden as if general
- shell script duplication that increases drift risk

## Output format
- Findings only
- Highest severity first
- Include exact files and reasoning
- Do not pad with compliments
