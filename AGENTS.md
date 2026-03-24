# AGENTS.md

## Mission
Maintain and extend this repository with minimal, reviewable changes.
Preserve architecture and artifact contracts unless the task explicitly authorizes redesign.

## Repository focus
This repo implements a narrow static-to-SMT-to-runtime bridge for cross-entry UAF research,
with a current emphasis on Linux arm64 KVM workflows and the MOCK handoff path.

## Operating rules
- Read relevant files before editing.
- For any non-trivial task, update `plans/current.md` before making code changes.
- Prefer the smallest correct diff over broad refactors.
- Preserve file and interface stability where possible.
- Do not silently change JSON schema shape or field names.
- Do not add dependencies unless necessary.
- Do not modify lockfiles unless a dependency change is required.
- When behavior changes, add or update tests or smoke coverage.
- Run the narrowest relevant validation first, then broader validation if needed.
- Surface assumptions and unsupported cases explicitly instead of hiding them.

## Architecture guardrails
- Preserve the artifact flow:
  `UAFX warning -> candidate.json -> witness_plan.json -> witness.syz / MOCK seed`
- Keep transforms deterministic up to the dynamic stage.
- SMT must use stock Z3 behavior; do not introduce solver-side modifications.
- Unsupported cases should fail clearly with typed or structured messages.
- Preserve provenance and reproducibility metadata when extending schemas or outputs.
- Prefer additive extension points over redesigning existing stages.

## Review priorities
When asked to review, prioritize:
1. correctness
2. regressions
3. schema drift
4. security and unsafe assumptions
5. missing tests or validation
6. maintainability

## Expected output format
End substantive tasks with:
1. Summary
2. Changed files
3. Validation run
4. Risks / assumptions
5. Follow-ups

## Project pointers
Primary areas usually involved:
- `uaf-bridge/extractor/`
- `uaf-bridge/mapping/`
- `uaf-bridge/smt/`
- `uaf-bridge/runtime/`
- `mock/tools/`
- `mock/scripts/`
- `docs/plans/`
- `scripts/`

## Validation discipline
Prefer targeted checks before broad checks.
Examples:
- schema validation
- narrow bridge unit tests
- witness emission smoke
- mock seed import smoke
- remote-target preflight
