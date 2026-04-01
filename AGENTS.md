# AGENTS.md

## Mission

Implement and maintain Madelin as an artifact-driven research system for realizing UAFX-style cross-entry UAF candidates dynamically.

## Primary system goal

Preserve the static-to-dynamic pipeline:

UAFX
→ bridge / witness planner
→ state-aware syzkaller backend
→ candidate-aware crash triage / repro

## Architectural guardrails

- Preserve `candidate.json` semantics.
- Preserve `witness_plan.json` semantics.
- Do not silently change ordering semantics.
- Do not broaden support claims beyond validated behavior.
- Keep bridge and runtime as separate stages.
- Prefer narrow, reproducible artifacts over implicit logic.

## Current v1 backend scope

Supported:
- Linux
- syzkaller-based execution
- KASAN/KCOV-backed feedback
- arm64 KVM-oriented resource chains
- sequential cross-entry candidates with hard-order constraints
- candidate-aware crash triage

Not supported in v1:
- broad subsystem support
- arbitrary schedule synthesis
- deep symbolic execution
- deep syzkaller fork
- generalized dependency-graph mutation for all subsystems

## Required engineering behavior

Before changes:
- map touched codepaths
- identify producer/consumer boundaries
- identify the narrowest validation path

During changes:
- prefer smallest safe diff
- update docs, imports, scripts, and references consistently
- record schema impact if artifacts are touched

After changes:
- run narrow smoke checks first
- record validation evidence
- update durable project memory

## Review priorities

1. Contract preservation
2. Validation integrity
3. Reproducibility
4. Maintainability
5. Narrow support claims