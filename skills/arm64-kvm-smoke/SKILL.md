---
name: arm64-kvm-smoke
description: Use when validating narrow arm64 KVM demo or smoke paths across bridge and MOCK integration.
---

# arm64-kvm-smoke

## Use this when
- A task touches arm64 KVM mapping
- A task changes witness emission for KVM flows
- A task affects MOCK seed preparation or KVM-specific relations
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
