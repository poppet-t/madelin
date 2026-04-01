---
name: validator-smoke-runner
description: Run the narrowest correct preflight and smoke validation for the task and summarize what passed, failed, or remains unverified.
---

# validator-smoke-runner

## Use this when
- a code change is ready for validation
- preflights need to be run
- witness or harness smoke is needed
- remote target checks are relevant
- a task touches arm64 KVM mapping, witness emission, or seed preparation

## Read first
- `context/commands.md`
- `plans/current.md`
- `plans/schema-impact.md` if present

## Steps
1. Run environment or remote-target preflights first.
2. Run the narrowest smoke relevant to the touched stage.
3. Escalate only if narrower checks pass.
4. Run broader demo paths only after narrower checks succeed.
5. Write `plans/validation-report.md`.

## Output
- commands run
- pass/fail
- not run
- environment limits
- whether results show correctness or only non-regression

## Guardrails
- do not claim broader coverage than was actually run
- distinguish correctness evidence from non-regression evidence
- surface environment blockers explicitly

