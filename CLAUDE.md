# CLAUDE.md

## Project identity
This repository is a kernel-security research monorepo for finding bugs in the Linux arm64 KVM subsystem.

It uses a 3-layer architecture:

1. `uafx/`
   Static producer of cross-entry UAF candidates.

2. `uaf-bridge/`
   Canonical translator:
   - UAFX warning -> richer export
   - richer export -> candidate.json
   - candidate.json -> witness_plan.json via Z3
   - candidate + plan -> mock_seed.json / pseudo-syz witness / proof artifacts

3. `mock/`
   Dynamic consumer:
   - imports bridge-generated mock_seed.json
   - generates seeded corpus / relation bias / bridge bias
   - runs Healer-based fuzzing against arm64 KVM targets

The architectural goal is:
static evidence -> structural witness -> seeded dynamic exploration

## Tooling split
This repository uses a hybrid AI workflow:

- Claude Code is primarily used for:
  - discovery
  - architecture
  - subsystem understanding
  - experiment design
  - review
  - identifying bottlenecks and next-step planning

- Codex is primarily used for:
  - bounded implementation
  - mechanical edits
  - tests
  - verification loops
  - scripts
  - patching review findings

This split is intentional. Keep it stable unless there is a strong reason not to.

## Product and research objective
Primary target:
- Linux kernel
- arm64
- KVM

Primary outcome:
- improve the probability of finding real bugs in arm64 KVM by using UAFX-guided structure to bias dynamic fuzzing

This repository is not trying to produce perfect semantic reproducers from static analysis alone.
It is trying to produce useful, structurally grounded execution guidance that makes dynamic fuzzing more effective.

## Directory map
- `uafx/` — static cross-entry UAF candidate producer
- `uaf-bridge/` — normalization, mapping, Z3 solving, seed export, proof packaging
- `mock/` — Healer-based seed consumer, bias importer, fuzzing runner
- `docs/` — plans, workflow docs, review notes, ADRs

## Architectural boundaries
### UAFX responsibilities
UAFX should:
- discover cross-entry UAF candidates
- recover structural facts such as escape/fetch, ordering, and concurrency hints
- export machine-readable warning evidence

UAFX should not:
- know about MOCK internals
- generate dynamic seed programs directly
- hardcode fuzzing behavior

### uaf-bridge responsibilities
The bridge should:
- normalize UAFX exports
- attach KVM/arm64-specific entry and syscall templates
- encode structural feasibility into Z3
- emit witness plans and seed intent
- preserve grounded vs heuristic distinctions

The bridge should not:
- become a full semantic KVM state synthesizer
- directly execute fuzzing
- absorb raw fuzzer internals

### MOCK responsibilities
MOCK should:
- ingest bridge-produced seed intent
- create seeded corpora and mutation bias
- preserve important resource/setup/order hints
- fuzz KVM-heavy execution families

MOCK should not:
- parse raw UAFX warnings
- embed static-analysis-specific logic all over the core
- silently depend on fragile bridge-only assumptions without documenting them

## Non-negotiable engineering rules
- Preserve the three-layer architecture.
- Do not silently merge concerns between UAFX, bridge, and MOCK.
- Preserve explicit grounded vs heuristic distinctions in exported artifacts.
- Prefer minimal patches over broad rewrites.
- Keep changes reversible and debuggable.
- Every behavior change should have targeted verification.
- Do not claim “bug-finding improvement” without a comparison plan.
- Never mark work complete without stating:
  - what changed
  - what was tested
  - what remains heuristic / unproven

## arm64 KVM-specific guidance
KVM is fd/ioctl-centric and setup-heavy.

Typical setup chains include:
- `open("/dev/kvm")`
- `KVM_CREATE_VM`
- `KVM_CREATE_VCPU`
- optional `KVM_CREATE_DEVICE`
- then VCPU / VM / device ioctls such as:
  - `KVM_RUN`
  - `KVM_ARM_VCPU_INIT`
  - `KVM_SET_ONE_REG`
  - `KVM_GET_ONE_REG`
  - `KVM_SET_DEVICE_ATTR`

This means prefix preservation and setup dependency awareness matter.
Blind randomization is less useful than seeded structure here.

When reviewing or planning, always ask:
- does this change preserve the KVM setup/resource chain?
- does this improve structural focus on KVM paths?
- does this reduce blind search or only create prettier artifacts?

## Coding standards
- Prefer small focused functions.
- Preserve current repo conventions within each subproject.
- Avoid hidden global state unless there is a strong runtime reason.
- Add comments when intent would otherwise be unclear.
- Avoid over-abstraction.
- Keep glue code explicit and inspectable.

## Security and reliability rules
- Treat static-analysis output as input, not as ground truth.
- Preserve provenance from UAFX where possible.
- Do not silently invent unsupported KVM semantics.
- Prefer deterministic artifact generation for bridge outputs.
- Surface failures honestly.

## Testing and verification
Use the smallest relevant verification first.

Default verification order:
1. local/unit tests for touched files
2. artifact generation checks
3. importer/adapter tests
4. dry-run seeded workflow
5. short seeded smoke run
6. seeded vs unseeded comparison only when ready

Typical commands:
- Bridge tests:
  - `cd uaf-bridge && ./.venv_ci/bin/pytest -q`
- Bridge demo:
  - `cd uaf-bridge && bash scripts/run_end_to_end_kvm_demo.sh`
- MOCK tests:
  - `cd mock && PYTHONPATH=. python3 -m unittest`
- Seed prep:
  - `cd mock && bash scripts/prepare_kvm_seed.sh`
- Seeded dry-run / smoke run:
  - `cd mock && bash scripts/run_kvm_seed_fuzz.sh ...`

## Expected planning format
When planning work, produce:
1. goal
2. why now
3. current bottleneck
4. scope
5. assumptions
6. impacted files/modules
7. risks
8. implementation order
9. verification plan
10. rollback / fallback notes
11. definition of done

## Expected review format
When reviewing:
1. compare current state against the plan file
2. identify architecture drift
3. identify correctness issues
4. identify missing tests
5. identify weak heuristics or overclaims
6. propose the smallest next patch set

## Handoff discipline
When handing work to Codex:
- create/update `docs/plans/<task>.md`
- write the exact next bounded step
- list allowed files to edit
- list exact verification commands
- note what must remain unchanged

When receiving work from Codex:
- review against the plan, not only the diff
- verify architecture boundaries were preserved
- verify tests actually exercise the changed behavior
- check whether the patch improved real bug-hunting structure, not only artifact generation

## Completion criteria
A task is complete only when:
- it matches the written plan
- relevant checks were run
- scope creep is explained or removed
- remaining limitations are stated
- the next bottleneck is clear