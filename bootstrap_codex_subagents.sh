#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${1:-.}"
SKILLS_ROOT="${REPO_ROOT}/skills"

mkdir -p "$REPO_ROOT/.codex"
mkdir -p "$REPO_ROOT/context"
mkdir -p "$REPO_ROOT/plans/archive"
mkdir -p "$SKILLS_ROOT"

# ------------------------------------------------------------------------------
# Base scaffold files
# ------------------------------------------------------------------------------

cat > "$REPO_ROOT/AGENTS.md" <<'EOF'
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
EOF

cat > "$REPO_ROOT/.codex/config.toml" <<'EOF'
approval_policy = "on-request"
sandbox_mode = "workspace-write"

[sandbox_workspace_write]
writable_roots = ["."]
EOF

cat > "$REPO_ROOT/context/overview.md" <<'EOF'
# Overview

## What this repository is for
This repository implements a prototype UAF witness bridge that connects:
1. static warning output
2. normalized candidate extraction
3. SMT-based structural feasibility solving
4. runtime witness or seed emission
5. downstream MOCK-oriented fuzzing handoff

## Current emphasis
The current implementation is intentionally narrow and optimized for:
- stable artifact contracts
- deterministic transforms up to runtime
- explicit unsupported-case handling
- Linux arm64 KVM-oriented entry families and demos

## What success looks like
A successful change:
- preserves cross-stage contracts
- keeps schema drift controlled
- improves witness feasibility or runtime usefulness
- remains reviewable and testable
- does not broaden the system accidentally

## What to avoid
- architecture rewrites during implementation tasks
- silent schema changes
- hidden changes to ordering semantics
- “helpful” generalization that breaks narrow supported paths
- mixing planning, implementation, and review in one uncontrolled pass
EOF

cat > "$REPO_ROOT/context/architecture.md" <<'EOF'
# Architecture

## Pipeline
The system is organized as a staged pipeline:

`warning -> candidate extraction -> mapping/classification -> SMT encoding/solve -> witness plan -> runtime emission -> MOCK import/seeded fuzzing`

## Main stages

### 1. Extraction / normalization
Transforms raw static-warning material into a canonical `candidate.json`.

Responsibilities:
- normalize warning structure
- preserve provenance
- recover relevant contexts
- attach cross-entry metadata
- keep output stable and machine-readable

### 2. Mapping / entry classification
Maps candidate contexts into supported entry classes and syscall-template fragments.

Responsibilities:
- identify supported entry families
- classify entry kinds such as ioctl/read/write/sysfs
- attach manual or template-assisted mappings
- stay conservative when evidence is weak

### 3. SMT stage
Encodes structural feasibility constraints into stock Z3 and extracts a witness plan.

Responsibilities:
- encode ordering requirements
- represent partial-order constraints
- model basic resource and alias relationships
- produce SAT/UNSAT outcomes with useful witness metadata

### 4. Runtime emission
Converts candidate + witness plan into a deterministic pseudo-syzkaller scaffold or MOCK-facing seed material.

Responsibilities:
- preserve plan ordering
- emit stable prefixes
- keep dynamic repair in the runtime/fuzzing stage, not the bridge stages
- expose relations/hints to downstream tooling

### 5. MOCK handoff
Imports bridge outputs into MOCK seed and bias formats for targeted fuzzing.

Responsibilities:
- preserve stable resource prefixes
- preserve intended ordering edges
- make bridge intent visible downstream
- fail clearly when the imported seed is structurally unsupported

## Design invariants
- Bridge stages should be deterministic given the same inputs.
- Dynamic fuzzing is where argument/value healing can occur.
- Artifact boundaries matter more than local convenience.
- Narrow support is preferable to fake generality.
EOF

cat > "$REPO_ROOT/context/invariants.md" <<'EOF'
# Invariants

## Contract invariants
- Preserve the pipeline contract:
  `warning -> candidate.json -> witness_plan.json -> emitted scaffold / imported seed`
- Do not rename or remove schema fields without explicit authorization.
- If a schema must change, update every affected producer, consumer, validator, and smoke path.

## Solver invariants
- Use stock Z3 behavior.
- Keep solver encoding focused on structural feasibility, not speculative semantics.
- Preserve ordering and resource predicates where they are already part of the candidate model.

## Runtime invariants
- Preserve deterministic emission for identical candidate + witness-plan inputs.
- Do not move dynamic healing logic earlier into the bridge.
- Keep stable ordering and resource prefixes visible to downstream tooling.

## Support-boundary invariants
- Keep narrow support explicit.
- Unsupported cases must fail clearly.
- Do not silently widen support without tests and documentation.

## Research invariants
- Preserve provenance.
- Preserve reproducibility.
- Prefer explainable, inspectable artifacts over clever implicit behavior.
EOF

cat > "$REPO_ROOT/context/commands.md" <<'EOF'
# Commands

## Environment checks
- `python3 uaf-bridge/scripts/check_env.py`
- `bash mock/scripts/check_remote_target.sh`

## Narrow smoke paths
- `bash scripts/e2e_witness_smoke.sh`
- `bash scripts/e2e_harness_smoke.sh`

## Bridge flow
- `python3 -m extractor ...`
- `python3 uaf-bridge/smt/solve_candidate.py ...`
- `python3 uaf-bridge/runtime/emit_witness_syz.py ...`

## Demo path
- `bash uaf-bridge/scripts/run_end_to_end_kvm_demo.sh`

## MOCK-side import
- `python3 mock/tools/import_bridge_seed.py ...`

## What to run first
1. environment preflight
2. narrow smoke relevant to touched stage
3. stage-specific validation
4. broader end-to-end demo only if needed
EOF

cat > "$REPO_ROOT/context/current-status.md" <<'EOF'
# Current Status

## Working assumptions
- The repository is currently strongest on narrow KVM-oriented demonstration paths.
- The major value is in stable staged contracts rather than broad workload coverage.
- Prefix preservation, ordering semantics, and downstream enforcement remain critical evaluation areas.

## Use this file to record
- what was completed in the last session
- what is currently working
- what is only partially implemented
- what validation is trustworthy
- what remains blocked by environment constraints
EOF

cat > "$REPO_ROOT/context/known-issues.md" <<'EOF'
# Known Issues

## Typical risk areas
- schema drift between stages
- bridge-to-MOCK ordering semantics not being enforced strongly enough downstream
- demo-only paths becoming mistaken for general support
- environment-dependent verifier or kernel-fuzzing workflows
- shell-script sprawl and duplicated workflow logic

## Use this file to track
- open technical debt
- weak validation coverage
- missing typed errors
- unsupported cases that need better surfacing
- reproducibility gaps
EOF

cat > "$REPO_ROOT/plans/current.md" <<'EOF'
# Current Plan

## Task
[Describe the task in one paragraph.]

## Constraints
- preserve architecture
- preserve artifact contracts
- do not silently change schemas
- prefer the smallest correct diff
- keep unsupported cases explicit

## Relevant files
- [file]
- [file]
- [file]

## Plan
1. Inspect the exact call path and artifact boundary involved.
2. Identify the smallest insertion point.
3. Implement the minimal correct change.
4. Add or update validation.
5. Run targeted checks.
6. Summarize changes, risks, and follow-ups.

## Validation
- [command]
- [command]

## Done when
- [ ] behavior implemented
- [ ] no accidental schema drift
- [ ] validation completed
- [ ] summary written
EOF

# ------------------------------------------------------------------------------
# Helper to create skill directories and starter SKILL.md files
# ------------------------------------------------------------------------------

create_skill() {
  local skill_name="$1"
  local skill_description="$2"
  local skill_body="$3"
  local skill_dir="${SKILLS_ROOT}/${skill_name}"

  mkdir -p "${skill_dir}"
  cat > "${skill_dir}/SKILL.md" <<EOF
---
name: ${skill_name}
description: ${skill_description}
---

${skill_body}
EOF
}

# ------------------------------------------------------------------------------
# 11 subagent skills
# ------------------------------------------------------------------------------

create_skill "repo-cartographer" \
"Map the relevant codepath, boundaries, and affected files for a maintenance task before implementation begins." \
'# repo-cartographer

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
'

create_skill "task-planner" \
"Turn a request into the smallest safe execution plan with explicit constraints, files, validation, and done criteria." \
'# task-planner

## Use this when
- the task is non-trivial
- the request spans multiple files
- implementation should be staged
- validation needs to be planned before coding

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
'

create_skill "extractor-maintainer" \
"Maintain the warning-to-candidate extraction and normalization layer while preserving provenance and candidate contract stability." \
'# extractor-maintainer

## Use this when
- editing `uaf-bridge/extractor/`
- changing warning import logic
- changing candidate normalization
- adjusting provenance handling

## Read first
- `AGENTS.md`
- `context/architecture.md`
- `context/invariants.md`
- `plans/current.md`

## Steps
1. Locate the exact extraction path involved.
2. Identify candidate fields produced or affected.
3. Make the smallest correct change.
4. Note any candidate schema impact.
5. Update validation or smoke coverage if needed.

## Output
- summary of extraction change
- changed files
- affected candidate fields
- validation run
- risks / assumptions

## Guardrails
- preserve provenance
- do not silently change candidate schema shape
- keep extractor responsibilities separate from solver/runtime logic
'

create_skill "mapper-maintainer" \
"Maintain entry classification and syscall-template mapping conservatively, with explicit supported and unsupported behavior." \
'# mapper-maintainer

## Use this when
- editing `uaf-bridge/mapping/`
- changing entry classification
- updating manual driver maps
- updating syscall template fragments

## Read first
- `AGENTS.md`
- `context/architecture.md`
- `context/invariants.md`
- `plans/current.md`

## Steps
1. Identify the mapping or classification boundary touched.
2. Confirm what evidence drives the mapping.
3. Implement the smallest correct change.
4. State supported and unsupported cases clearly.
5. Update stage-specific validation if needed.

## Output
- summary
- changed files
- classification or mapping impact
- validation run
- risks / assumptions

## Guardrails
- stay conservative when evidence is weak
- prefer explicit unsupported cases over broad guesses
- do not blur mapping logic into extraction or solver logic
'

create_skill "solver-maintainer" \
"Maintain SMT encoding and witness extraction while preserving structural-feasibility semantics and stock Z3 usage." \
'# solver-maintainer

## Use this when
- editing `uaf-bridge/smt/`
- changing ordering constraints
- changing alias/resource predicates
- changing witness extraction from SAT models

## Read first
- `AGENTS.md`
- `context/architecture.md`
- `context/invariants.md`
- `plans/current.md`

## Steps
1. Identify the exact constraint family or extraction path touched.
2. Determine whether candidate or witness fields are affected.
3. Implement the smallest correct solver change.
4. Keep the change focused on structural feasibility.
5. Update or add targeted validation.

## Output
- summary
- changed files
- constraint impact
- validation run
- risks / assumptions

## Guardrails
- use stock Z3 behavior
- avoid speculative semantic modeling
- do not silently change witness-plan shape
'

create_skill "runtime-emitter-maintainer" \
"Maintain witness and pseudo-syzkaller emission while preserving ordering, determinism, and stage boundaries." \
'# runtime-emitter-maintainer

## Use this when
- editing `uaf-bridge/runtime/`
- changing witness emission
- changing pseudo-syzkaller generation
- changing ordering preservation in emitted outputs

## Read first
- `AGENTS.md`
- `context/architecture.md`
- `context/invariants.md`
- `plans/current.md`

## Steps
1. Identify the exact runtime emission boundary touched.
2. Confirm what witness-plan fields are consumed.
3. Make the smallest correct change.
4. Check ordering preservation and deterministic output.
5. Update validation if needed.

## Output
- summary
- changed files
- emitted artifact impact
- validation run
- risks / assumptions

## Guardrails
- preserve deterministic emission for identical inputs
- do not move dynamic healing into earlier bridge stages
- do not silently reinterpret witness-plan semantics
'

create_skill "mock-handoff-maintainer" \
"Maintain the bridge-to-MOCK import path, including seed import, relations, and bias generation, without hidden coupling." \
'# mock-handoff-maintainer

## Use this when
- editing `mock/tools/import_bridge_seed.py`
- changing relations or bias generation
- changing seed import behavior
- changing KVM seed preparation scripts

## Read first
- `AGENTS.md`
- `context/architecture.md`
- `context/invariants.md`
- `plans/current.md`

## Steps
1. Identify the exact imported artifact and consumer path.
2. Confirm stable prefix and ordering assumptions.
3. Make the smallest correct importer or handoff change.
4. State downstream assumptions explicitly.
5. Update validation if needed.

## Output
- summary
- changed files
- downstream assumption list
- validation run
- risks / assumptions

## Guardrails
- keep the bridge and MOCK connected by explicit artifacts, not hidden coupling
- preserve stable prefix intent where applicable
- fail clearly on unsupported imported shapes
'

create_skill "schema-guardian" \
"Check for producer-consumer contract drift around candidate and witness artifacts and block silent schema changes." \
'# schema-guardian

## Use this when
- any artifact field may change
- extraction, solver, emitter, or importer may alter schema expectations
- ordering semantics encoded in artifacts may change

## Read first
- `AGENTS.md`
- `context/invariants.md`
- relevant schema files
- relevant producers
- relevant consumers
- relevant smoke scripts
- `plans/current.md`

## Steps
1. List producers of the touched artifact.
2. List consumers of the touched artifact.
3. Classify the change as additive, risky, or breaking.
4. Write `plans/schema-impact.md`.
5. Refuse silent drift.

## Output
- producer list
- consumer list
- compatibility verdict
- required downstream updates
- explicit warning if the change is breaking

## Guardrails
- do not approve silent producer-consumer mismatch
- treat ordering semantics changes as schema-impacting unless proven otherwise
- prefer explicit impact notes over implicit compatibility claims
'

create_skill "validator-smoke-runner" \
"Run the narrowest correct preflight and smoke validation for the task and summarize what passed, failed, or remains unverified." \
'# validator-smoke-runner

## Use this when
- a code change is ready for validation
- preflights need to be run
- witness or harness smoke is needed
- remote target checks are relevant

## Read first
- `context/commands.md`
- `plans/current.md`
- `plans/schema-impact.md` if present

## Steps
1. Run preflights first.
2. Run the narrowest smoke relevant to the touched stage.
3. Escalate only if narrower checks pass.
4. Write `plans/validation-report.md`.

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
'

create_skill "reviewer-regression" \
"Review diffs for regressions, schema drift, unsafe assumptions, and missing validation, with findings only and highest severity first." \
'# reviewer-regression

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
'

create_skill "status-curator" \
"Update durable project memory after work completes, including current status, known issues, and plan archive notes." \
'# status-curator

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
'

# ------------------------------------------------------------------------------
# Optional starter artifacts for subagent handoffs
# ------------------------------------------------------------------------------

cat > "$REPO_ROOT/plans/repo-map.md" <<'EOF'
# Repo Map

## Request
[Summarize the maintenance request.]

## Relevant files
- [file]
- [file]
- [file]

## Producer -> consumer boundaries
- [producer] -> [consumer]
- [producer] -> [consumer]

## Likely validation points
- [command]
- [command]

## Risks of touching the wrong stage
- [risk]
- [risk]
EOF

cat > "$REPO_ROOT/plans/schema-impact.md" <<'EOF'
# Schema Impact

## Touched artifact
[candidate.json | witness_plan.json | other]

## Producers
- [producer]

## Consumers
- [consumer]

## Compatibility verdict
[additive | risky | breaking]

## Required follow-up updates
- [update]
- [update]

## Notes
[details]
EOF

cat > "$REPO_ROOT/plans/validation-report.md" <<'EOF'
# Validation Report

## Commands run
- [command]

## Passed
- [result]

## Failed
- [result]

## Not run
- [result]

## Environment limits
- [limit]

## Evidence level
[correctness | non-regression | partial]
EOF

echo "Codex subagent scaffold created under: $REPO_ROOT"
echo
echo "Skills root: $SKILLS_ROOT"
echo "Created 11 subagent skills:"
echo "  - repo-cartographer"
echo "  - task-planner"
echo "  - extractor-maintainer"
echo "  - mapper-maintainer"
echo "  - solver-maintainer"
echo "  - runtime-emitter-maintainer"
echo "  - mock-handoff-maintainer"
echo "  - schema-guardian"
echo "  - validator-smoke-runner"
echo "  - reviewer-regression"
echo "  - status-curator"
echo
echo "Next steps:"
echo "  1. Review AGENTS.md and context/commands.md."
echo "  2. Adjust SKILLS_ROOT near the top if your Codex setup expects a different repo-local skills path."
echo "  3. Start Codex in this repo and ask it to read AGENTS.md and context/*."
echo "  4. For a real task, begin with repo-cartographer and task-planner."