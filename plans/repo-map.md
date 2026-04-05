# Repo map

## Durable orchestration surface
- `plans/current.md` — current implementation status and remaining gaps
- `plans/repo-map.md` — producer/consumer boundaries
- `plans/schema-impact.md` — contract preservation notes
- `plans/validation-report.md` — exact validation evidence

## Static producers
- `uafx/` — primary static analysis producer
- `uaf-bridge/uafx_fork/tools/export_bridge_candidate.py` — raw warning -> bridge export
- `uaf-bridge/extractor/import_uafx_bridge_export.py` — bridge export -> `candidate.json`
- `uaf-bridge/extractor/normalize_candidate.py` — raw warning normalization support

## Pack metadata and bridge logic
- `targets/<pack>/manifest.json` — target-pack metadata, lifecycle hints, seed hints, fixture pointers
- `uaf-bridge/mapping/target_registry.py` — target-pack registry + context resolution
- `uaf-bridge/mapping/entry_classifier.py` — normalized entry-kind classification
- `uaf-bridge/mapping/manual_driver_map.yaml` — explicit entry-function overrides
- `uaf-bridge/mapping/syscall_templates.py` — pack-aware template generation

## Witness planning and bridge outputs
- `uaf-bridge/smt/encode_candidate.py` — structural SMT encoding
- `uaf-bridge/smt/solve_candidate.py` — deterministic `witness_plan.json` generation
- `uaf-bridge/runtime/emit_witness_syz.py` — pack-aware witness emission
- `uaf-bridge/runtime/validate_witness.py` — witness contract validation
- `uaf-bridge/harness/generate_harness.py` — KVM-specific + generic harness generation
- `uaf-bridge/harness/generic_templates.py` — non-KVM harness families

## Runtime consumer (canonical)
- `backend/syz-guided/state_model/build_state_model.py` — `candidate.json` + `witness_plan.json` -> runtime artifacts
- `backend/syz-guided/seedgen/synthesize_seeds.py` — pack-aware syzkaller seed synthesis
- `backend/syz-guided/orchestrator/campaign.py` — bounded dry-run campaign lifecycle
- `backend/syz-guided/triage/report.py` — `triage_report_v1.json`
- `backend/syz-guided/pack_registry.py` — backend-side pack manifest resolution

## io_uring real-runtime lane
- `backend/syz-guided/runtime/io_uring_lane.py` — per-seed execution, dmesg, triage, evidence artifacts
- `backend/syz-guided/triage/io_uring_verdict.py` — 6-class subsystem-aware verdict classifier
- `backend/syz-guided/triage/io_uring_symbols.py` — io_uring symbol tables for crash enrichment
- `backend/syz-guided/scripts/run_io_uring_vm_campaign.sh` — 8-step campaign pipeline for arm64 Linux VMs
- Evidence artifacts: execution_trace_summary, preserved_prefix_report, edge_coverage_summary,
  concurrency_window_report, candidate_alignment_report, runtime_verdict

## net (nf_tables/netfilter) real-runtime lane
- `backend/syz-guided/runtime/net_lane.py` — per-seed execution, dmesg, triage, evidence artifacts
- `backend/syz-guided/triage/net_verdict.py` — 6-class subsystem-aware verdict classifier
- `backend/syz-guided/triage/net_symbols.py` — net symbol tables for crash enrichment (50+ functions, 15+ files)
- `backend/syz-guided/scripts/run_net_vm_campaign.sh` — 8-step campaign pipeline for arm64 Linux VMs
- Evidence artifacts: execution_trace_summary, preserved_prefix_report, edge_coverage_summary,
  concurrency_window_report, candidate_alignment_report, runtime_verdict

## Validation and fixtures
- `uaf-bridge/uafx_fork/samples/raw_uafx_*_warning.json` — raw producer fixtures
- `uaf-bridge/extractor/sample_uafx_*_bridge_export.json` — bridge-export fixtures
- `backend/syz-guided/tests/fixtures/packs/<pack>/` — bridge-generated backend fixtures
- `backend/syz-guided/scripts/smoke_pack.sh` — backend-only dry-run proof by pack
- `scripts/e2e_target_pack_smoke.sh` — root-level UAFX-first dry-run proof by pack
- `scripts/e2e_witness_smoke.sh` — bridge witness-only smoke by pack
- `scripts/e2e_harness_smoke.sh` — bridge harness-only smoke by pack

## Artifact flow

```text
raw UAFX warning
  -> bridge export
  -> candidate.json
  -> witness_plan.json
  -> witness.syz / harness.c
  -> state_model_v1.json
  -> target_profile.json
  -> relation_graph_v1.json
  -> seed_*.prog + seed_manifest.json
  -> campaign_summary.json
  -> triage_report_v1.json

io_uring real-runtime lane (extends the above):
  -> seed_*.prog execution via syz-execprog
  -> dmesg collection
  -> per-seed triage_report_v1.json
  -> execution_trace_summary.json
  -> preserved_prefix_report.json
  -> edge_coverage_summary.json
  -> concurrency_window_report.json
  -> candidate_alignment_report.json
  -> runtime_verdict.json

net (nf_tables) real-runtime lane (same evidence artifact set):
  -> seed_*.prog execution via syz-execprog (nf_tables lifecycle seeds)
  -> dmesg collection (CONFIG_NF_TABLES + CONFIG_KASAN required)
  -> per-seed triage_report_v1.json
  -> execution_trace_summary.json
  -> preserved_prefix_report.json
  -> edge_coverage_summary.json
  -> concurrency_window_report.json (delete+dump overlap tracking)
  -> candidate_alignment_report.json (net_enrichment + subsystem_relevance)
  -> runtime_verdict.json
```

## Contract boundaries
- `candidate.json` and `witness_plan.json` remain the stable bridge/runtime handoff.
- `mock_seed.json` may still be emitted by the bridge as an auxiliary artifact, but `mock/` is not a runtime stage.
- Runtime schemas remain `state_model/v1`, `target_profile/v1`, `relation_graph/v1`, `triage_report/v1`.
