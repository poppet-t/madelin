---
name: smoke-test-authoring
description: Add narrow, hardware-light smoke tests that prove end-to-end artifact flow per target pack.
---

# smoke-test-authoring

## Use this when
- adding new pack smokes that must run without special hardware
- adding end-to-end dry-run proofs: fixture -> candidate -> plan -> backend artifacts -> triage artifact

## Read first
- `AGENTS.md`
- `context/commands.md`
- `plans/current.md`
- `plans/validation-report.md` (to follow existing evidence style)

## Steps
1. Define the smallest smoke per pack that proves the artifact chain.
2. Ensure the smoke exits nonzero on failure and prints the exact failure stage.
3. Make the smoke deterministic (fixed fixture inputs, fixed output dirs).
4. Add CI-friendly unit tests where possible; keep smokes minimal and fast.
5. Record exact command lines and outcomes in `plans/validation-report.md`.

## Guardrails
- distinguish dry-run artifact proofs from live kernel execution proofs
- do not require nested virtualization, passthrough, or privileged host features for non-KVM packs

