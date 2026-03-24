# Invariants

## Contract invariants
- Preserve the pipeline contract:
  `warning -> candidate.json -> witness_plan.json -> emitted scaffold / imported seed`
- Do not rename or remove schema fields without explicit authorization.
- If a schema must change, update every affected producer, consumer, validator, and smoke path.

## Solver invariants
- Use stock Z3 behavior.
- Keep solver encoding focused on structural feasibility, not speculative semantics.
- Preserve ordering and resource predicates where they are already part of the candidate model.

## Runtime invariants
- Preserve deterministic emission for identical candidate + witness-plan inputs.
- Do not move dynamic healing logic earlier into the bridge.
- Keep stable ordering and resource prefixes visible to downstream tooling.

## Support-boundary invariants
- Keep narrow support explicit.
- Unsupported cases must fail clearly.
- Do not silently widen support without tests and documentation.

## Research invariants
- Preserve provenance.
- Preserve reproducibility.
- Prefer explainable, inspectable artifacts over clever implicit behavior.
