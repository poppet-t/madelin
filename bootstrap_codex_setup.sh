#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${1:-.}"

mkdir -p "$REPO_ROOT/.codex"
mkdir -p "$REPO_ROOT/context"
mkdir -p "$REPO_ROOT/plans/archive"
mkdir -p "$REPO_ROOT/skills/create-plan"
mkdir -p "$REPO_ROOT/skills/witness-bridge-task"
mkdir -p "$REPO_ROOT/skills/schema-change-check"
mkdir -p "$REPO_ROOT/skills/arm64-kvm-smoke"
mkdir -p "$REPO_ROOT/skills/code-review-security"

cat > "$REPO_ROOT/AGENTS.md" <<'EOF'
# AGENTS.md

## Mission
Maintain and extend this repository with minimal, reviewable changes.
Preserve architecture and artifact contracts unless the task explicitly authorizes redesign.

## Repository focus
This repo implements a narrow static-to-SMT-to-runtime bridge for cross-entry UAF research,
with a current emphasis on artifact-driven validation in hardware-light arm64 Linux VMs,
scoped by target packs (legacy/initial pack: arm64 KVM).

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
  `UAFX warning/bridge-export -> candidate.json -> witness_plan.json -> witness.syz -> backend/syz-guided`
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
- `uafx/`
- `uaf-bridge/extractor/`
- `uaf-bridge/mapping/`
- `uaf-bridge/smt/`
- `uaf-bridge/runtime/`
- `backend/syz-guided/`
- `targets/`
- `plans/`
- `scripts/`

## Validation discipline
Prefer targeted checks before broad checks.
Examples:
- schema validation
- narrow bridge unit tests
- witness emission smoke
- backend seedgen/campaign/triage smokes
- remote-target preflight
EOF

cat > "$REPO_ROOT/.codex/config.toml" <<'EOF'
# Project-scoped Codex config
# You can add or change `model = "..."`
# based on the Codex-capable model you actually use.

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
5. downstream syzkaller runtime backend consumption

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

`warning -> candidate extraction -> mapping/classification -> SMT encoding/solve -> witness plan -> runtime emission -> backend/syz-guided consumption`

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
Converts candidate + witness plan into a deterministic pseudo-syzkaller scaffold and/or small harnesses for runtime consumption.

Responsibilities:
- preserve plan ordering
- emit stable prefixes
- keep dynamic repair in the runtime/fuzzing stage, not the bridge stages
- expose relations/hints to downstream tooling

### 5. Runtime backend handoff
Consumes bridge outputs in a syzkaller-based runtime backend (seed synthesis, campaign orchestration, triage).

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
  `warning -> candidate.json -> witness_plan.json -> emitted scaffold -> backend runtime artifacts`
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
- `bash backend/syz-guided/scripts/smoke_seedgen.sh`

## Narrow smoke paths
- `bash scripts/e2e_witness_smoke.sh`
- `bash scripts/e2e_harness_smoke.sh`

## Bridge flow
- `python3 -m extractor ...`
- `python3 uaf-bridge/smt/solve_candidate.py ...`
- `python3 uaf-bridge/runtime/emit_witness_syz.py ...`

## Demo path
- `bash uaf-bridge/scripts/run_end_to_end_kvm_demo.sh`

## Backend consumption
- `python3 backend/syz-guided/state_model/build_state_model.py ...`
- `python3 backend/syz-guided/seedgen/synthesize_seeds.py ...`

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
- bridge-to-backend ordering semantics not being enforced strongly enough downstream
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

cat > "$REPO_ROOT/skills/create-plan/SKILL.md" <<'EOF'
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
EOF

cat > "$REPO_ROOT/skills/witness-bridge-task/SKILL.md" <<'EOF'
---
name: witness-bridge-task
description: Use for changes to the UAFX -> candidate -> SMT -> runtime bridge. Enforces contract preservation, narrow diffs, and validation discipline.
---

# witness-bridge-task

## Use this when
- Editing extraction, mapping, SMT, runtime emission, or backend-facing handoff logic
- Changing artifact boundaries
- Adding support for a narrow new entry family
- Debugging witness feasibility or scaffold generation

## Required reads
- `AGENTS.md`
- `context/architecture.md`
- `context/invariants.md`
- `plans/current.md`

## Required behavior
- Preserve artifact contracts unless explicitly authorized otherwise.
- Keep unsupported cases explicit.
- Prefer additive extension points over redesign.
- Preserve provenance and reproducibility metadata.
- Do not blur stage responsibilities.

## Checklist
Before editing, identify whether the change affects:
- candidate schema
- witness plan schema
- runtime emitter assumptions
- ordering semantics
- stable resource prefix expectations

## Execution sequence
1. Find the exact producer and consumer boundaries touched.
2. Confirm whether this is:
   - local logic change
   - schema change
   - ordering/constraint change
   - runtime-only emission change
3. Implement the smallest correct diff.
4. Add or update validation for the touched stage.
5. Run narrow checks first.
6. Report assumptions and unverified paths.

## Final output format
- Summary
- Changed files
- Boundary touched
- Validation run
- Risks / assumptions
- Follow-ups
EOF

cat > "$REPO_ROOT/skills/schema-change-check/SKILL.md" <<'EOF'
---
name: schema-change-check
description: Use when a change may affect candidate.json, witness_plan.json, or downstream artifact consumers.
---

# schema-change-check

## Purpose
Prevent accidental schema drift across bridge stages.

## Use this when
- Adding fields
- Renaming fields
- Reinterpreting field meaning
- Changing ordering semantics encoded in artifacts
- Updating validators or typed consumers

## Required reads
- `AGENTS.md`
- `context/invariants.md`
- schema files
- producer code
- consumer code
- relevant smoke scripts

## Procedure
1. List every producer of the touched artifact.
2. List every consumer of the touched artifact.
3. Identify whether the change is:
   - additive backward-compatible
   - additive but requires downstream handling
   - breaking
4. Update all affected validations.
5. Document the impact in the final summary.

## Refusal rule
If the requested task would create silent schema drift, stop and report that explicitly.
EOF

cat > "$REPO_ROOT/skills/arm64-kvm-smoke/SKILL.md" <<'EOF'
---
name: arm64-kvm-smoke
description: Use when validating the legacy/initial arm64 KVM pack across bridge, backend, and runtime proof paths.
---

# arm64-kvm-smoke

## Use this when
- A task touches arm64 KVM mapping
- A task changes witness emission for KVM flows
- A task affects backend seed preparation or KVM-specific relations
- A task updates remote-target preflight behavior

## Required reads
- `AGENTS.md`
- `context/commands.md`
- `plans/current.md`

## Validation order
1. Run environment or remote-target preflights first.
2. Run the narrowest witness smoke relevant to the touched stage.
3. Run harness smoke only if needed.
4. Run broader demo paths only after narrower checks succeed.

## Reporting
Always state:
- what was run
- what was not run
- what environment constraints remain
- whether the result demonstrates correctness or only non-regression
EOF

cat > "$REPO_ROOT/skills/code-review-security/SKILL.md" <<'EOF'
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
EOF

echo "Codex scaffold created under: $REPO_ROOT"
echo
echo "Next steps:"
echo "  1. Review .codex/config.toml and optionally add your preferred model."
echo "  2. Fill in real commands in context/commands.md if needed."
echo "  3. Start Codex in this repo and ask it to read AGENTS.md and context/*."
