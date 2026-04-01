---
name: schema-guardian
description: Check for producer-consumer contract drift around candidate and witness artifacts and block silent schema changes.
---

# schema-guardian

## Use this when
- any artifact field may change
- adding, renaming, or reinterpreting fields
- extraction, solver, emitter, or importer may alter schema expectations
- ordering semantics encoded in artifacts may change
- updating validators or typed consumers

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
- if the requested task would create silent schema drift, stop and report that explicitly

