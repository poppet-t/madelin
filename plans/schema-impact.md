# Schema impact

## Preserved contracts (no changes)

- `candidate.json` (candidate/v1): consumed read-only by state model builder
- `witness_plan.json` (witness_plan/v1): consumed read-only by state model builder
- `mock_seed.json` (mock_seed/v1): not touched by backend

## New runtime artifacts

### state_model_v1.json
Schema version: `state_model/v1`
Producer: `backend/syz-guided/state_model/build_state_model.py`
Consumers: seed synthesizer, orchestrator, mutator, triage

Contains:
- candidate_id, schema_version
- subsystem, arch, target_family
- source_artifacts (candidate path, witness plan path)
- loc0, loc1 (free/use site metadata)
- resource_chain (ordered resource dependencies with types)
- phases (bootstrap, configure, trigger — each with syscalls)
- precedence_edges (hard ordering from barriers)
- sticky_calls (calls that must not be removed)
- immutable_prefix_len (length of bootstrap prefix to protect)
- favored_suffix_calls (calls likely to trigger free/use)
- score_weights (prefix_valid, resource_chain, phase_progress, target_signal, order_preserved)

### target_profile.json
Schema version: `target_profile/v1`
Producer: `backend/syz-guided/state_model/build_state_model.py`
Consumers: orchestrator scoring, triage matching

Contains:
- candidate_id, schema_version
- focus_frames (functions near free/use sites)
- focus_files (source files near free/use sites)
- free_use_hints (function, file, line for loc0/loc1)
- preferred_syscalls (from template calls)
- candidate_signal_rules (KASAN UAF match conditions)

### relation_graph_v1.json
Schema version: `relation_graph/v1`
Producer: `backend/syz-guided/state_model/build_state_model.py`
Consumers: mutator relation guard, orchestrator relation tracker

Contains:
- candidate_id, schema_version
- nodes (resource and syscall nodes with types and phases)
- edges (resource_flow and must_precede edges)
- mutation_constraints (immutable prefix, suffix-only mutation, preserve-resource-chain rules)

### triage_report_v1.json
Schema version: `triage_report/v1`
Producer: `backend/syz-guided/triage/report.py`
Consumers: human review, repro wrapper

Contains:
- candidate_id, schema_version
- crash_id, timestamp
- crash_summary (type, allocator, stack frames)
- candidate_match (focus_frame_hit, focus_file_hit, free_use_hint_match, uaf_type_match, match_score)
- state_summary (prefix_valid, resource_chain_intact, phase_reached, order_preserved)
- verdict (confirmed, plausible, unrelated, insufficient_data)
- evidence (raw crash excerpt, matched frames, matched files)

## vm_validator impact

**None.** The `vm_validator/` subsystem is a pure consumer of existing runtime
artifacts and a user of the existing triage interface. It does not modify or extend any
schema. Its only new output (`vm_run_log.json`) is internal and disposable — no schema
definition needed.

Verified interfaces (Phase 0):
- Consumes: `state_model_v1.json`, `target_profile.json`, `seed_*.prog` — all unchanged
- Triage entry: `triage.report.build_triage_report(crash_text, tp, sm, program_calls)` — unchanged
- Produces: `triage_report_v1.json` via existing `triage/report.py` — schema unchanged

## Compatibility verdict

All changes are **additive**. No existing artifacts are modified. The new backend is a pure consumer of bridge artifacts and producer of new runtime artifacts.
