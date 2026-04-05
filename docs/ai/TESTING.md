# Testing Guide

## Philosophy
Run the smallest relevant checks first. Expand only when the patch or risk justifies it.

## Testing layers in this repo

### Layer 1 — artifact/contract tests (bridge-side)
Purpose:
- preserve `candidate.json` and `witness_plan.json` semantics
- keep transforms deterministic up to runtime
- ensure unsupported cases fail explicitly

Examples:
- UAFX bridge-export import shape
- entry classification normalization
- syscall template selection
- witness-plan determinism and ordering semantics

### Layer 2 — runnable-witness / harness emission tests
Purpose:
- validate that emitted `witness.syz` and/or micro-harnesses match the selected plan and template family
- validate pack-specific constraints (resource flow, thread metadata, family selection)

Examples:
- `uaf-bridge/runtime/emit_witness_syz.py` + `validate_witness.py`
- `uaf-bridge/harness/generate_harness.py`

### Layer 3 — backend dry-run proofs (no special hardware)
Purpose:
- prove end-to-end artifact consumption and runtime artifact generation

Examples:
- `backend/syz-guided/state_model/build_state_model.py`
- `backend/syz-guided/seedgen/synthesize_seeds.py`
- orchestrator/campaign dry-run
- triage report emission against synthetic crash logs

### Layer 4 — live execution proofs (hardware-light by default)
Purpose:
- execute at least one `.prog` against a real kernel and feed output into triage

Examples:
- `vm_validator` one-shot execution under QEMU TCG
- Linux KVM host one-shot execution for the `kvm` pack
- bounded `syz-manager` campaign (Linux KVM host)

## Default verification order
1. nearby unit tests
2. artifact-level contract tests
3. backend dry-run smokes
4. optional one-shot runtime execution proof
5. broader campaigns only after the above pass

## Required in summaries
Every implementation summary must include:
- commands run
- pass/fail
- whether verification was artifact-level, backend dry-run, or live execution
- any untested packs/families
