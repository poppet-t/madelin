# Current Plan

## Task
Add an operator-facing OpenClaw handoff for the Linux arm64 KVM workflow so a VPS-hosted agent can understand the repo structure, the bridge-to-MOCK system boundaries, the exact run path, the current support limits, and the maintenance rules before it starts running or repairing the system.

## Hard Constraints
- preserve the artifact flow `warning -> candidate.json -> witness_plan.json -> witness.syz / MOCK seed`
- do not silently change schemas, field names, or ordering semantics
- keep support claims narrow and truthful
- treat Linux arm64 KVM as the primary runnable target
- prefer documentation and handoff clarity over new abstractions
- do not redesign architecture for an AI handoff doc
- keep edits reviewable and scoped to docs plus minimal pointers

## Non-Goals
- no code-path redesign
- no schema changes
- no new dependency management
- no false claim that the current macOS host can execute the real arm64 KVM launch

## Smallest Relevant File Set
- `plans/current.md`
- `README.md`
- `docs/ai/WORKFLOW.md`
- `docs/ai/TESTING.md`
- `plans/repo-map.md`
- `plans/validation-report.md`
- `context/current-status.md`
- `context/known-issues.md`
- `uaf-bridge/README.md`
- `mock/README.md`
- new OpenClaw-facing handoff doc under `docs/ai/`

## Execution Plan
1. Add one concise OpenClaw runbook that explains the monorepo structure, stage ownership, exact arm64 KVM run sequence, validation boundaries, and common maintenance traps.
2. Point the main project README at that runbook so operators can find it quickly.
3. Produce a high-signal OpenClaw prompt that tells the agent exactly how to validate, what not to change, how to report blockers, and what counts as success.
4. Run a light doc sanity check by reading the updated files and confirming the prompt matches the repo’s current validated boundary.

## Validation
1. Read back the new runbook.
2. Read back the updated README pointer.
3. Ensure the final OpenClaw prompt matches the documented Linux-host workflow and current blocker language.

## Done Criteria
- the repo contains one explicit OpenClaw/operator handoff doc
- the doc explains repo structure, systems, run order, support limits, and maintenance expectations
- the README points operators to the new doc
- the final prompt is specific enough that OpenClaw can run and maintain the system on the VPS without inventing architecture
