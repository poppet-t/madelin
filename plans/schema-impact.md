# Schema impact

## Preserved contracts

No schema version changed in this pivot.

- `candidate.json` remains `candidate/v1`
- `witness_plan.json` remains `witness_plan/v1`
- `state_model_v1.json` remains `state_model/v1`
- `target_profile.json` remains `target_profile/v1`
- `relation_graph_v1.json` remains `relation_graph/v1`
- `triage_report_v1.json` remains `triage_report/v1`

## Additive producer-side changes

The UAFX bridge-export payload now carries additive target metadata so the importer can
preserve pack selection deterministically:

- `arch`
- `kernel_area`
- `subsystem`
- `target_family`
- `entry_summary.entry_candidates[*].entry_kind_hint`

These are producer-side fields in the bridge-export shape; they do not change the public
`candidate.json` or `witness_plan.json` schema versions.

## Additive repo-level contracts

New pack manifests live under `targets/<pack>/manifest.json` and define:

- target metadata and maturity
- supported entry kinds
- lifecycle/state-machine templates
- witness constraints
- seed synthesis hints
- triage metadata
- fixture pointers

This is additive repository metadata, not a new runtime artifact schema.

## Deterministic witness-plan behavior

`witness_plan.json` remains structurally unchanged, but plan generation is now explicitly
canonicalized:

- SAT/UNSAT is still driven by the SMT encoding
- emitted `ordered_steps` are canonicalized from the event set + partial order
- emitted thread assignments are canonicalized from `flow`/`min_threads`
- arbitrary solver timestamps are no longer exposed in the plan output

This preserves ordering semantics while making the artifact deterministic across runs.

## Compatibility verdict

The pivot is additive and contract-preserving:

- bridge/runtime handoff schemas are unchanged
- KVM remains supported as a legacy pack
- new target packs are added without widening support claims beyond validated dry-run behavior
- unsupported cases remain explicit rather than silently falling back
