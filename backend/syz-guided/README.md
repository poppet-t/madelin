# backend/syz-guided

Candidate-directed syzkaller backend for UAFX cross-entry UAF realization.

## Scope

- Hardware-light arm64 Linux target packs
- Legacy/initial pack: `kvm`
- Initial software-reachable packs: `io_uring`, `net`, `bpf`, `fs`
- Consumes `candidate.json` + `witness_plan.json` from `uaf-bridge/`
- Produces runtime artifacts: state model, target profile, relation graph, seeds
- Orchestrates bounded fuzzing campaigns
- Performs candidate-aware triage

## Quick start

```bash
# Build runtime artifacts from bridge fixtures
python3 state_model/build_state_model.py \
    --candidate tests/fixtures/candidate.json \
    --witness-plan tests/fixtures/witness_plan.json \
    --out-dir /tmp/syz-guided-out/

# Synthesize seeds
python3 seedgen/synthesize_seeds.py \
    --state-model /tmp/syz-guided-out/state_model_v1.json \
    --out-dir /tmp/syz-guided-out/seeds/

# Run bounded campaign (no real syzkaller needed for skeleton)
python3 orchestrator/campaign.py \
    --artifacts-dir /tmp/syz-guided-out/ \
    --seeds-dir /tmp/syz-guided-out/seeds/ \
    --work-dir /tmp/syz-guided-campaign/ \
    --max-iterations 10
```

## Smoke tests (any platform)

```bash
bash scripts/smoke_seedgen.sh
bash scripts/smoke_campaign.sh
bash scripts/smoke_triage.sh
bash scripts/smoke_vm_validator.sh   # preflight-only or full TCG boot (macOS/Linux)
bash scripts/smoke_pack.sh --pack kvm
bash scripts/smoke_pack.sh --pack io_uring
bash scripts/smoke_pack.sh --pack net
bash scripts/smoke_pack.sh --pack bpf
bash scripts/smoke_pack.sh --pack fs
```

## Linux KVM scripts (Linux only — fail honestly on macOS)

```bash
bash scripts/check_linux_kvm_host.sh --kernel ... --disk ... --ssh-key ...
bash scripts/run_linux_kvm_one_shot.sh --kernel ... --disk ... --ssh-key ... --syz-execprog ... --syz-executor ... --prog ... --out-dir ...
bash scripts/run_linux_syz_manager.sh --config ... --out-dir ... [--timeout 600]
```

See `plans/linux-kvm-runbook.md` for the full execution guide.

## Unit tests

```bash
python3 tests/test_state_model.py -v
python3 tests/test_seedgen.py -v
python3 tests/test_score.py -v
python3 tests/test_triage.py -v
python3 tests/test_relation_guard.py -v
python3 tests/test_vm_validator.py -v
```

## Layout

```
schemas/           JSON schemas for runtime artifacts
state_model/       Build state model from bridge artifacts
seedgen/           Synthesize syzkaller seeds
orchestrator/      Campaign, scoring, queueing
mutator/           Prefix-safe mutation
triage/            KASAN parsing, candidate matching, reports
repro/             Candidate-preserving repro wrapper
integration/       Syzkaller runner interface
vm_validator/      One-shot QEMU TCG arm64 validation (macOS, validated)
scripts/           Smoke tests + Linux KVM helper scripts
tests/             Unit tests + fixtures (88 tests total)
```

## Artifacts produced

| Artifact | Schema | Producer |
|----------|--------|----------|
| state_model_v1.json | state_model/v1 | state_model/build_state_model.py |
| target_profile.json | target_profile/v1 | state_model/build_state_model.py |
| relation_graph_v1.json | relation_graph/v1 | state_model/build_state_model.py |
| triage_report_v1.json | triage_report/v1 | triage/report.py |
| seed_*.prog | (syzkaller format) | seedgen/synthesize_seeds.py |
| campaign_summary.json | (internal) | orchestrator/campaign.py |
