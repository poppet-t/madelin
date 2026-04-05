# Net Lab Target

This directory defines the **lab-only** synthetic net target for Madelin's `nf_tables` workflow.

## What it proves

- The current guest-backed `net` lane can boot a prepared arm64 lab kernel reproducibly.
- The lane can stage executors, execute a bounded seed, capture console and dmesg, triage the result,
  preserve crash artifacts, and produce a deterministic lab-facing verdict.
- The lane can confirm a controlled `nf_tables` free/use bug only when real runtime evidence passes
  the strict proof bar.

## What it does not prove

- Broad `net` subsystem coverage
- Real-world novelty
- CVE worthiness
- Exploitability

## Synthetic target

- Expected free frame: `nf_tables_destroy_set`
- Expected use frame: `nf_tables_dump_set`
- Expected source file: `net/netfilter/nf_tables_api.c`
- Proof patch: `targets/net/proof/nftables-controlled-proof-uaf.patch`

The current lab target reuses the existing proof-mode kernel flow. It is deliberately narrow and
exists only to prove that Madelin's artifact-driven lane can catch and classify a controlled net bug.
