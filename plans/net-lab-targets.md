# Net Lab Targets

## Scope

This file tracks the bounded **lab-only** net targets that Madelin may use for proof runs.

Only runtime evidence counts as proof. Ranking helpers and AI summaries are advisory only.

## Current lab target

- Target: synthetic `nf_tables` free/use bug
- Lab manifest: `targets/net/lab/manifest.json`
- Proof patch: `targets/net/proof/nftables-controlled-proof-uaf.patch`
- Expected free frame: `nf_tables_destroy_set`
- Expected use frame: `nf_tables_dump_set`
- Expected source file: `net/netfilter/nf_tables_api.c`
- Preferred seed order:
  1. `seed_delete_dump.prog`
  2. `seed_dump_delete.prog`
  3. `seed_update_dump_delete.prog`

## Required runtime artifacts

- `runtime/kernel_provenance.json`
- `runtime/source_frame_summary.json`
- `runtime/lab_run_bundle.json`
- `runtime/blocker_report.json` when proof is not achieved
- `crashes/manual_known_bug_review.json`
- preserved crashing `.prog`
- `repro/*/repro_summary.json` when a crash occurs

## Success states

- `confirmed lab bug`
- `candidate-correlated crash`
- `no bug confirmed; exact blocker`
- `patch candidate for reproduced lab bug`

## Non-claims

- No broader net subsystem support
- No claim of novelty or CVE status
- No proof outside the saved runtime evidence
