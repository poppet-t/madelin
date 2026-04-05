# Madelin — Claude Code entrypoint

Read before making changes:

- @AGENTS.md
- @context/overview.md
- @context/architecture.md
- @context/invariants.md
- @context/commands.md
- @context/current-status.md
- @context/known-issues.md
- @plans/current.md
- @plans/repo-map.md
- @plans/schema-impact.md
- @plans/io_uring-runtime-proof.md
- @plans/net-runtime-proof.md
- Treat `backend/syz-guided/scripts/run_net_vm_campaign.sh` and `docs/ai/OPENCLAW-RUNBOOK.md` as the authoritative nf_tables live-validation entrypoints.
- For the arm64 QEMU net lane, prefer `syzkaller-runtime-export/arm64-live-ready.qcow2`
  with `--guest-extra-append 'init=/root/madelin-guest-init.sh'` and guest-resident
  `/root/syz-execprog` + `/root/syz-executor` unless a faster validated guest path exists.

## Skills

Bounded role procedures — use the matching skill when a task fits its trigger.

- @skills/task-planner/SKILL.md
- @skills/repo-cartographer/SKILL.md
- @skills/schema-guardian/SKILL.md
- @skills/validator-smoke-runner/SKILL.md
- @skills/reviewer-regression/SKILL.md
- @skills/status-curator/SKILL.md
- @skills/witness-bridge-task/SKILL.md
- @skills/extractor-maintainer/SKILL.md
- @skills/mapper-maintainer/SKILL.md
- @skills/solver-maintainer/SKILL.md
- @skills/runtime-emitter-maintainer/SKILL.md
- @skills/target-pack-design/SKILL.md
- @skills/witness-plan-contract/SKILL.md
- @skills/subsystem-fixture-generation/SKILL.md
- @skills/smoke-test-authoring/SKILL.md
- @skills/candidate-aware-triage-extension/SKILL.md

## Core rules

- Read first, modify second.
- Preserve `candidate.json` and `witness_plan.json` semantics.
- Do not silently change field meanings, ordering semantics, or support claims.
- Prefer artifact-driven interfaces over hidden conversational assumptions.
- Prefer stock or lightly patched syzkaller over deep forks.
- Keep v1 narrow — see `context/overview.md` for scope.
- Prefer the smallest safe diff.
- Record validation evidence in `plans/validation-report.md`.
- Update `context/current-status.md` and `context/known-issues.md` when facts change.
