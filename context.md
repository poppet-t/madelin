# Context for Codex / future contributors

## Project name
UAF Witness Bridge

## Why this exists
This project links static cross-entry kernel UAF analysis to dynamic validation.

The static side can identify plausible cross-entry bugs but usually stops at relational evidence:
- where the free happens
- where the use happens
- which entrypoints may be involved
- what ordering or aliasing facts must hold

The dynamic side can execute syscall programs and find crashes, but it needs a concrete plan.

This repository builds the missing bridge:
static candidate -> SMT witness -> runnable syscall prefix

## Core design principle
Do not modify Z3.
Use stock Z3 as a solver backend.
Put the project’s novelty in:
- candidate normalization
- entry-to-syscall mapping
- constraint encoding
- witness extraction
- dynamic realization
- proof packaging

## Architecture summary
There are four major layers:

1. extractor/
   Consumes static warning output and emits canonical `candidate.json`.

2. mapping/
   Maps static entrypoints to one or more syscall templates.

3. smt/
   Encodes the candidate into Z3 and extracts a witness plan.

4. runtime/
   Converts witness plans into runnable syz-style prefixes and runtime artifacts.

A fifth layer, proof/, packages outputs for debugging and research reporting.

## Initial assumptions
- v1 is intentionally narrow.
- We only support a small set of entry surfaces first.
- Exact argument synthesis is deferred; SMT solves schedule/structure first.
- Runtime mutation/repair handles concrete values later.

## Supported v1 entry classes
- file_ioctl
- file_read
- file_write
- sysfs_show
- sysfs_store

## v1 constraint philosophy
### Put in SMT
- event ordering
- thread assignment
- resource existence predicates
- alias/same-object relations when statically grounded
- lock/condition ordering where simple and explicit

### Keep out of SMT for v1
- exact ioctl values
- exact struct field contents
- detailed environment setup
- complex value search
- subsystem-specific magic constants

## Canonical pipeline
1. Parse static warning
2. Normalize into candidate
3. Classify entrypoints
4. Attach syscall templates
5. Encode SMT problem
6. Solve SAT/UNSAT
7. Extract witness plan
8. Emit syz-style prefix
9. Execute / package artifacts

## Important implementation rules
- Save every intermediate artifact to disk.
- Every file must carry `candidate_id`.
- Keep schemas explicit and versioned.
- Make modules composable and testable in isolation.
- Prefer JSON over ad hoc text output.
- Prefer deterministic transforms before dynamic stages.

## Directory intent
- `schemas/` — JSON schema files for candidate and witness plan
- `extractor/` — warning parsers and normalizers
- `mapping/` — entry classifiers and syscall templates
- `smt/` — Z3 encoding, solving, and model extraction
- `runtime/` — witness emission and runtime helpers
- `proof/` — artifact packaging and crash matching
- `tests/` — focused unit/integration tests

## Candidate schema intent
`candidate.json` should be the stable interface between static extraction and the rest of the system.

It should include:
- identity
- provenance
- raw warning payload
- normalized sites and contexts
- mapped entries
- constraints
- ranking / status metadata

## Witness plan intent
`witness_plan.json` should be the stable interface between the solver and runtime.

It should include:
- SAT/UNSAT status
- model values
- ordered steps
- threads
- barriers
- predicates
- runtime hints

## First milestone
The first real milestone is:
one warning JSON -> one candidate.json -> one witness_plan.json

Do not begin by integrating everything at once.

## Coding conventions
- Python 3.11+
- type hints required
- pydantic/dataclasses acceptable
- argparse for CLIs
- pytest for tests
- black/ruff-friendly formatting
- all CLIs return non-zero on failure
- write readable logs, not only exceptions

## Research conventions
- preserve provenance from original warning data
- do not silently infer unsupported facts
- mark guessed mappings explicitly
- separate “grounded” from “heuristic” fields where possible

## Anti-goals
- giant monolithic script
- hidden state in temp files
- solver logic mixed with runtime execution logic
- subsystem-specific hacks in the core schema layer

## What good looks like
A good patch makes one layer sharper without breaking the interfaces.
A good commit produces more explicit artifacts, better tests, or more reliable narrowing of candidate realization.