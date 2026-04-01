# Architecture

## Static pipeline

warning
→ candidate extraction
→ mapping/classification
→ SMT encode/solve
→ witness plan

## Dynamic pipeline

candidate.json
→ witness_plan.json
→ state_model_v1.json
→ target_profile.json
→ relation_graph_v1.json
→ synthesized syzkaller seeds
→ syz-guided orchestrator
→ syzkaller executor/manager
→ KASAN/KCOV kernel
→ candidate-aware triage
→ repro/minimization
→ verdict artifacts

## Backend design principles

- Preserve bootstrap prefixes.
- Preserve producer→consumer resource chains.
- Mutate suffixes before prefixes.
- Score programs by candidate progress, not only coverage.
- Keep candidate-aware policy outside syzkaller unless light patching is clearly justified.

## Intended backend layout

backend/syz-guided/
- schemas/
- state_model/
- seedgen/
- orchestrator/
- mutator/
- triage/
- repro/
- integration/
- scripts/
- tests/