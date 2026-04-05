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
- For the net live lane, prefer the replacement `syzkaller-runtime-export/arm64-live-ready.qcow2`
  plus the minimal guest init (`init=/root/madelin-guest-init.sh`) over the slow full-system
  Ubuntu boot path when the goal is staged live validation under arm64 QEMU TCG.

## Current v1 backend scope

Supported:
- Linux
- syzkaller-based execution
- KASAN/KCOV-backed feedback
- target-pack oriented resource chains (legacy/initial validated slice: arm64 KVM)
- io_uring real-runtime validation lane (dry-run proven, live execution pending)
- net (nf_tables/netfilter) staged live-validation lane on arm64 QEMU with strict preflight, layered verdicting, repro artifacts, and known-bug hygiene
- sequential cross-entry candidates with hard-order constraints
- candidate-aware crash triage
- subsystem-aware triage with io_uring and net symbol enrichment

Not supported in v1:
- broad subsystem support without target-pack fixtures, contracts, and validation evidence
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
