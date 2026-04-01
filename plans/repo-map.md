# Repo map

## Static producers (unchanged)
- uafx/
- uaf-bridge/extractor/ → candidate.json
- uaf-bridge/mapping/ → entry classification, syscall templates
- uaf-bridge/smt/ → witness_plan.json
- uaf-bridge/runtime/ → witness .syz, mock_seed.json (bridge output; not a runtime path)
- uaf-bridge/schemas/ → candidate.schema.json, witness_plan.schema.json, mock_seed.schema.json

## Runtime consumer (canonical)
- backend/syz-guided/schemas/ → state_model_v1, target_profile, relation_graph_v1, triage_report_v1
- backend/syz-guided/state_model/ → build_state_model.py, validate_state_model.py
- backend/syz-guided/seedgen/ → synthesize_seeds.py, emit_seed_manifest.py
- backend/syz-guided/orchestrator/ → campaign.py, queue.py, score.py
- backend/syz-guided/mutator/ → prefix_safe_mutator.py, relation_guard.py
- backend/syz-guided/triage/ → parse_kasan.py, match_candidate.py, report.py
- backend/syz-guided/repro/ → candidate_repro.py
- backend/syz-guided/integration/ → syzkaller_runner.py
- backend/syz-guided/scripts/ → smoke_seedgen.sh, smoke_campaign.sh, smoke_triage.sh, run_kvm_candidate.sh
- backend/syz-guided/tests/ → fixtures/, test_*.py

## Syzkaller reference tree
- syzkaller/ — clean upstream checkout of google/syzkaller (unmodified, no binaries)
- syzkaller-runtime-export/ — preserved arm64 KVM runtime environment from working run

## Disposable VM validator (designed, not yet implemented)
- backend/syz-guided/vm_validator/ — one-shot QEMU TCG runner for Mac
  - `__init__.py` — package marker
  - `preflight.py` — verify QEMU, kernel Image, disk image, syz-execprog, SSH key
  - `vm_runner.py` — boot QEMU TCG (aarch64, virt, cortex-a57), SSH wait, shutdown
  - `prog_injector.py` — scp seed_*.prog + syz-execprog into guest, execute via SSH
  - `log_collector.py` — pull dmesg from guest, extract KASAN section
  - `run_one.py` — top-level orchestrator: preflight → boot → inject → collect → triage → exit
  - consumes (from backend): state_model_v1.json, target_profile.json, seed_*.prog
  - consumes (operator-provided): kernel Image, arm64 disk image, SSH key, syz-execprog binary
  - produces: vm_run_log.json (internal, no schema), guest_dmesg.txt, crash_log.txt
  - produces (via existing triage/): triage_report_v1.json
  - triage integration: calls `triage.report.build_triage_report(crash_text, tp, sm, calls)`
  - does NOT use syz-manager or the syzkaller campaign loop
- backend/syz-guided/scripts/smoke_vm_validator.sh — end-to-end smoke (NEW)
- backend/syz-guided/tests/test_vm_validator.py — unit tests, no VM needed (NEW)

## Removed (legacy)
- mock/ — removed; was the legacy Healer-based consumer

## Artifact flow

```
candidate.json (bridge) ─┐
                         ├→ build_state_model.py → state_model_v1.json
witness_plan.json (bridge)┘                        │
                                                   ├→ target_profile.json
                                                   ├→ relation_graph_v1.json
                                                   └→ synthesize_seeds.py → .prog seeds + manifest
                                                                            │
                                                      campaign.py ←────────┘
                                                        │
                                                        ├→ syzkaller executor ($SYZ_DIR)
                                                        ├→ KASAN/KCOV feedback
                                                        └→ triage → triage_report_v1.json
```

## Touched contracts
- candidate.json: consumed only, not modified
- witness_plan.json: consumed only, not modified
- mock_seed.json: produced by bridge as artifact; not consumed by backend
- state_model_v1.json: new, produced by backend
- target_profile.json: new, produced by backend
- relation_graph_v1.json: new, produced by backend
- triage_report_v1.json: new, produced by backend

## Validation points
- Schema validation (all four new schemas)
- State model determinism for fixed inputs
- Seed parsing and prefix preservation
- Bounded campaign smoke
- Triage smoke
