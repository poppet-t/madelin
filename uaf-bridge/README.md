# UAF Witness Bridge (Research Prototype v1 Slice)

This repository is a single end-to-end research repo with **three clean layers** for finding bugs in **Linux arm64 KVM**:

1. **UAFX** = static cross-entry UAF candidate producer
2. **uaf-bridge** = canonical translator / normalizer / solver / seed exporter
3. **MOCK adapter** = dynamic handoff layer for corpus seeding and mutation guidance

The core contract is:

1. raw static warning JSON -> normalized `candidate.json`
2. normalized candidate -> Z3 `witness_plan.json`
3. candidate + witness plan -> deterministic pseudo-syz `witness.syz`
4. candidate + witness plan -> `mock_seed.json`
5. `mock_seed.json` -> MOCK-oriented adapter JSON / textual scaffold
6. candidate + witness plan + witness -> proof/debug bundle
7. raw UAFX warning -> richer UAFX bridge export -> imported KVM/arm64 candidate

The implementation stays intentionally narrow. It is **not** a full fuzzing platform, not a full syzkaller integration, and not a perfect KVM semantic reproducer. It is a **structural guidance bridge** for arm64 KVM bug hunting.

## What is implemented

- Runtime JSON schema validation for `candidate.json`, `witness_plan.json`, and `mock_seed.json`
- Deterministic JSON writing and stable step ordering
- Explicit candidate provenance and schema versions
- Explicit grounded vs heuristic entry metadata
- Explicit unsupported entry marking and unsupported reasons
- Structural Z3 witness synthesis with stable `ordered_steps`
- Deterministic pseudo-syz scaffold emission with proof/debug comments
- Deterministic `mock_seed.json` export for MOCK corpus seeding and mutation biasing
- MOCK adapter JSON import and deterministic textual scaffold emission
- Proof packaging into `proof/proof.md` and `proof/summary.json`
- Unit tests and subprocess integration tests for the full CLI pipeline

## Repository stages

- `extractor/` — warning intake and candidate normalization
- `mapping/` — entry classification and KVM/arm64 syscall template selection
- `smt/` — Z3 encoding and witness-plan extraction
- `runtime/` — pseudo-syz scaffold emission and `mock_seed.json` export
- `mock_adapter/` — clean handoff into MOCK-oriented seed/corpus/mutation representations
- `proof/` — proof/debug artifact packaging
- `schemas/` — runtime-enforced JSON schemas
- `tests/` — unit and integration coverage

## Supported v1 entry classes

- `file_ioctl`
- `file_read`
- `file_write`
- `sysfs_show`
- `sysfs_store`

Unsupported entries are never silently upgraded into supported ones. They remain explicit in `candidate.json`.

## Install

From `uaf-bridge/`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

## Architecture in plain English

### 1) UAFX

UAFX is the **static producer**. It discovers cross-entry UAF candidates, recovers escape/fetch-based alias relationships, and exports machine-readable evidence. UAFX is **not** the fuzzer.

### 2) uaf-bridge

The bridge is the **canonical contract boundary**. It:
- ingests rich UAFX export
- normalizes into `candidate.json`
- attaches KVM/arm64 setup and trigger templates
- solves structural feasibility into `witness_plan.json`
- exports `mock_seed.json`

### 3) MOCK

MOCK is the **dynamic consumer**. It should consume normalized bridge outputs instead of raw UAFX internals. The bridge tells MOCK:
- what KVM resource chain is needed first
- which syscall families to bias toward
- whether concurrency likely matters
- which orderings and predicates should be preserved
- which setup prefix should stay stable while later calls mutate

## CLI pipeline

Run commands from `uaf-bridge/`.

## UAFX -> bridge KVM/arm64 import slice

A narrow UAFX-side integration stub now lives under `uafx_fork/`.

What it does:
- reads one raw UAFX warning JSON record
- emits a richer bridge export JSON record for `arch/arm64/kvm`
- imports that export into canonical `candidate.json`

What it does **not** do yet:
- patch a real UAFX codebase in place automatically
- provide broad subsystem coverage
- claim grounded summaries for data that UAFX has not actually exported yet

### Example: raw UAFX warning -> richer export -> candidate

```bash
python -m uafx_fork.tools.export_bridge_candidate \
  --input uafx_fork/samples/raw_uafx_kvm_warning.json \
  --output out/uafx_kvm_bridge_export.json

python -m extractor.import_uafx_bridge_export \
  --input out/uafx_kvm_bridge_export.json \
  --output out/uafx_kvm_candidate.json
```

### 1) Normalize warning -> candidate

```bash
python3 -m extractor.normalize_candidate \
  --input extractor/sample_warn_data.json \
  --output out/candidate.json
```

### 2) Solve candidate -> witness plan

```bash
python3 -m smt.solve_candidate \
  --input out/candidate.json \
  --output out/witness_plan.json
```

### 3) Emit witness scaffold

```bash
python3 -m runtime.emit_witness_syz \
  --candidate out/candidate.json \
  --plan out/witness_plan.json \
  --output out/witness.syz
```

### 4) Export MOCK seed intent

```bash
python3 -m runtime.export_mock_seed \
  --candidate out/candidate.json \
  --plan out/witness_plan.json \
  --output out/mock_seed.json
```

### 5) Translate into MOCK-oriented adapter outputs

```bash
python3 -m mock_adapter.import_seed \
  --input out/mock_seed.json \
  --output out/mock_adapter.json

python3 -m mock_adapter.seed_to_mock_program \
  --input out/mock_seed.json \
  --output out/mock_program.txt
```

### 6) Package proof/debug artifacts

```bash
python3 -m proof.package_artifacts \
  --candidate out/candidate.json \
  --plan out/witness_plan.json \
  --witness out/witness.syz \
  --output-dir out/proof
```

## Artifact shape

### candidate.json

Carries:
- `candidate_id`
- `schema_version`
- `source`
- `provenance`
- `raw_warning`
- normalized locations
- explicit `entries[]` with:
  - `grounded`
  - `heuristic`
  - `supported`
  - `support_level`
  - `unsupported_reasons`
  - `syscall_templates`
- structural `constraints`
- `status` summary

### witness_plan.json

Carries:
- `candidate_id`
- `schema_version`
- `sat`
- `status`
- `ordered_steps`
- `threads`
- `barriers`
- `predicates`
- `execution_hints`
- `debug`

### witness.syz

This is a deterministic pseudo-syz scaffold for inspection, debugging, and downstream realization. It is not presented as a fully runnable syzkaller program.

### mock_seed.json

This is the key handoff into dynamic execution. It encodes:
- target / arch / subsystem
- entries involved and confidence levels
- setup sequence vs trigger sequence
- resource dependencies for `/dev/kvm`, VM fd, VCPU fd, and optional device fd paths
- ordering/barrier constraints
- predicates and concurrency hints
- mutation bias guidance for MOCK

It is a **structural seed intent model**, not a full runnable reproducer.

### proof bundle

`proof.package_artifacts` generates:
- `proof/proof.md`
- `proof/summary.json`

These summarize candidate identity, source metadata, entry classifications, SAT/UNSAT result, ordered steps, witness path, and limitations.

## Failure behavior

All CLIs:
- validate JSON inputs before use
- validate JSON outputs before writing when applicable
- print readable error messages to stderr
- return non-zero exit codes on failure
- include `candidate_id` in errors when available

## Tests

Run the full test suite:

```bash
pytest
```

The suite includes:
- normalization tests
- solver tests
- witness emission tests
- schema validation tests
- subprocess end-to-end CLI tests
- non-zero failure-path tests for malformed input

## Intentional v1 limits

Still intentionally unimplemented:
- exact ioctl values and concrete argument synthesis
- exact guest memory, register, and device-state synthesis for deep KVM semantics
- dynamic VM execution / syzkaller integration
- direct in-tree MOCK runtime embedding
- generalized driver-environment inference
- crash matching and runtime repair logic
- broad subsystem support beyond the narrow template taxonomy

## Example commands

```bash
cd uaf-bridge
python3 -m extractor.normalize_candidate --input extractor/sample_warn_data.json --output out/candidate.json
python3 -m smt.solve_candidate --input out/candidate.json --output out/witness_plan.json
python3 -m runtime.emit_witness_syz --candidate out/candidate.json --plan out/witness_plan.json --output out/witness.syz
python3 -m runtime.export_mock_seed --candidate out/candidate.json --plan out/witness_plan.json --output out/mock_seed.json
python3 -m mock_adapter.import_seed --input out/mock_seed.json --output out/mock_adapter.json
python3 -m mock_adapter.seed_to_mock_program --input out/mock_seed.json --output out/mock_program.txt
python3 -m proof.package_artifacts --candidate out/candidate.json --plan out/witness_plan.json --witness out/witness.syz --output-dir out/proof
pytest
```

## One-command demo run

```bash
cd uaf-bridge
bash scripts/run_end_to_end_kvm_demo.sh
```
