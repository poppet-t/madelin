# AI Workflow

## Goal
Use Claude Code and Codex together for the `madelin` project without context drift.

## Role split by phase

### Phase 1 — Discovery and bottleneck analysis
Default tool: Claude Code

Use for:
- codebase understanding
- subsystem review
- architecture analysis
- deciding whether the next bottleneck is in UAFX, bridge, or MOCK
- experiment design
- planning next bounded tasks

Deliverable:
- a plan file in `docs/plans/<task>.md`

### Phase 2 — Implementation
Default tool: Codex

Use for:
- bounded code changes
- scripts
- tests
- importer/exporter edits
- Rust config/CLI plumbing
- verification loops

Deliverable:
- code changes + verification summary

### Phase 3 — Review
Default tool: Claude Code

Use for:
- checking implementation against the written plan
- architecture drift review
- bug-hunting-value review
- heuristic-vs-grounded review
- missing test identification

Deliverable:
- review findings and minimal next patch set

### Phase 4 — Final patch + verification
Default tool: Codex

Use for:
- applying review fixes
- rerunning targeted checks
- producing final summary

Deliverable:
- final implementation summary and checks

## Handoff rules
Every handoff must include:
- task name
- goal
- current bottleneck
- assumptions
- exact next step
- relevant files
- verification commands
- definition of done

Never hand off raw conversation history when a plan file can be used.

## Scope control
For risky tasks, restrict by:
- subproject (`uafx`, `uaf-bridge`, `mock`)
- directory
- file list
- test scope

## Definition of done
A task is done when:
- code matches the written plan
- relevant checks ran
- risks are disclosed
- follow-ups are documented
- architecture boundaries remain clear