# MOCK removal audit

## Context

The `mock/` directory was removed from the repository. This audit classifies every
remaining reference so cleanup is systematic and nothing is silently broken.

## Findings

### mock/ directory itself

**Status: REMOVED** — all `mock/` files are unstaged deletions in git working tree.
No code in `mock/` is present on disk.

---

### References classified

#### SAFE TO DELETE (stale, points at removed directory)

| File | Reference | Reason |
|------|-----------|--------|
| `README.md` — Step 2 | `cd mock && cargo build --release` | Builds non-existent Rust crate |
| `README.md` — Step 4 | `cd mock && bash scripts/prepare_kvm_seed.sh` | References removed script |
| `README.md` — Step 5 | `cd mock && export SYZ_DIR=...` + prereq check | References removed scripts |
| `README.md` — Step 5b | `cd mock && bash scripts/check_remote_target.sh` | References removed script |
| `README.md` — Step 6 | `cd mock && bash scripts/run_kvm_seed_fuzz.sh --dry-run` | References removed script |
| `README.md` — Step 7 | `cd mock && bash scripts/run_kvm_seed_fuzz.sh` | References removed script |
| `README.md` — "Legacy seeded workflow (mock/)" section | Describes removed Healer path | Path no longer exists |
| `README.md` — "Optional Model Manager" section | `mock/tools/model_manager` | Directory removed |
| `README.md` — Testing / mock section | `cd mock && bash -n scripts/...` | References removed scripts |
| `README.md` — More Detail / `mock/README.md` | `mock/README.md` | File removed |
| `README.md` — Repository Layout / `mock/` entry | "Legacy dynamic consumer: imports bridge seeds..." | Directory removed |
| `README.md` — intro item 4 | `mock/ is the legacy consumer` | Directory removed |
| `context/current-status.md` | "Legacy mock/ path is untouched and still intact." | FALSE — mock/ removed |
| `plans/repo-map.md` — "Legacy runtime consumer" section | `mock/bridge_seed/`, `mock/tools/`, `mock/verdict/` | All removed |

#### MUST RENAME / UPDATE (stale wording but content still relevant)

| File | Reference | Action |
|------|-----------|--------|
| `context/known-issues.md` | "Legacy runtime/backend path may be incomplete or non-runnable." | Update: mock removed; backend is the runtime; risk is KVM environment sensitivity |
| `README.md` — uaf-bridge entry | "UAFX export → candidate.json → witness_plan.json → mock_seed.json" | Update: mock_seed.json is still a bridge output but not the canonical runtime path |
| `CLAUDE.md` | `@skills/mock-handoff-maintainer/SKILL.md` | Remove: skill references removed mock/ directory |
| `plans/current.md` | All phases marked incomplete | Update: v1 backend phases 1-5 are done; replace with migration/cleanup phase |

#### PRESERVE AS LEGACY / HISTORICAL

| File | Reference | Reason to keep |
|------|-----------|----------------|
| `uaf-bridge/schemas/mock_seed.schema.json` | mock_seed/v1 schema | Still produced by bridge as an artifact; keep schema for compatibility |
| `uaf-bridge/runtime/export_mock_seed.py` | Emits mock_seed.json | Bridge still produces this output; keep producer intact |
| `uaf-bridge/mock_adapter/` | mock_adapter layer | Bridge handoff layer; safe to keep as archived output stage |
| `uaf-bridge/out/uafx_kvm_mock_seed.json` | Generated artifact | Preserved demo output |
| `uaf-bridge/out/uafx_kvm_mock_adapter.json` | Generated artifact | Preserved demo output |
| `uaf-bridge/out/uafx_kvm_mock_program.txt` | Generated artifact | Preserved demo output |
| `skills/mock-handoff-maintainer/SKILL.md` | Skill definition | Keep as archive; remove reference from CLAUDE.md |
| `scripts/e2e_witness_smoke.sh` | References SYZ_DIR, MOCK_ROOT | Script exists but references removed paths; mark environment-limited |
| `scripts/e2e_harness_smoke.sh` | References SYZ_DIR, MOCK_ROOT | Same; mark environment-limited |
| `scripts/verify_candidate.sh` | MOCK_ROOT, MOCK_SEED_PATH, etc. | Full verification harness; references bridge outputs; keep but note dependencies |

#### SUSPICIOUS / NEEDS REVIEW

| File | Reference | Issue |
|------|-----------|-------|
| `README.md` — "Narrow Smoke Foundations" | `bash scripts/e2e_witness_smoke.sh` / `e2e_harness_smoke.sh` | These scripts have dead MOCK_ROOT references; smoke won't reach that branch, but confusing |
| `scripts/e2e_witness_smoke.sh` | `MOCK_ROOT` var | Dead variable; script may still be usable for bridge-only smoke path |
| `scripts/e2e_harness_smoke.sh` | `MOCK_ROOT` var | Same |

---

## Summary

**Minimum safe cleanup (this migration):**
1. Remove dead mock/ references from README.md, context/current-status.md, plans/repo-map.md
2. Update context/known-issues.md to reflect real current risks
3. Update plans/current.md and CLAUDE.md
4. Keep all bridge-side mock_seed artifacts untouched (bridge still produces them)
5. Keep skills/mock-handoff-maintainer/SKILL.md as archive but remove from CLAUDE.md

**Not done in this pass (acceptable deferred work):**
- Remove MOCK_ROOT references from e2e smoke scripts
- Review scripts/verify_candidate.sh MOCK references
- Decide whether to archive or remove uaf-bridge/mock_adapter/
