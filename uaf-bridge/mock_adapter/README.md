# MOCK Adapter

This directory is the clean handoff point between `uaf-bridge` and MOCK.

## Architecture

- **UAFX** finds static cross-entry UAF candidates and exports machine-readable evidence.
- **uaf-bridge** normalizes that evidence into `candidate.json`, solves for a structural witness in `witness_plan.json`, and exports `mock_seed.json`.
- **MOCK** consumes `mock_seed.json` through this adapter layer for:
  - **Mode A: offline corpus seeding**
  - **Mode B: targeted mutation biasing**

MOCK should never need to understand raw UAFX internals.

## Files

- `import_seed.py` — validates and translates `mock_seed.json` into a compact MOCK-oriented JSON form.
- `seed_to_mock_program.py` — renders a deterministic textual scaffold that makes the handoff human-auditable.

## Intended integration modes

### Mode A — offline corpus seeding

Use `setup_sequence` and `trigger_sequence` to create initial high-value KVM programs.
Keep the setup prefix stable so `/dev/kvm -> VM fd -> VCPU fd` dependencies are preserved.

### Mode B — mutation biasing

Use `mutation_hints` to:
- keep `preserve_prefix_len` calls stable
- bias towards `focus_syscall_families`
- prefer two-thread schedules when the seed says concurrency matters
- mutate mainly near trigger-side/use-side steps
- preserve ordering edges where the mutation engine can do so

## Example

```bash
python -m mock_adapter.import_seed --input out/uafx_kvm_mock_seed.json --output out/uafx_kvm_mock_adapter.json
python -m mock_adapter.seed_to_mock_program --input out/uafx_kvm_mock_seed.json --output out/uafx_kvm_mock_program.txt
```
