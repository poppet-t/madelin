# Proof Bundle for cand_2ffcd1fad7e62aba

## Summary
- Candidate ID: `cand_2ffcd1fad7e62aba`
- Candidate schema: `candidate/v1`
- Witness plan schema: `witness_plan/v1`
- Solver status: `sat`
- SAT: `True`
- Witness file: `out/witness.syz`
- Generated at (UTC): `2026-03-16T18:12:19.346132+00:00`

## Source
- Tool: `uaf-static-pass`
- Version: `0.1`
- Raw file: `extractor/sample_warn_data.json`

## Entry Classifications
- `demo_uaf_ioctl` -> `file_ioctl` (supported=True, support_level=grounded, unsupported_reasons=[])
- `demo_uaf_read` -> `file_read` (supported=True, support_level=grounded, unsupported_reasons=[])

## Ordered Steps
- step_index=0 timestamp=0 event=`free`
- step_index=1 timestamp=1 event=`use`
- step_index=2 timestamp=2 event=`escape`
- step_index=3 timestamp=3 event=`cleanup`
- step_index=4 timestamp=4 event=`fetch`
- step_index=5 timestamp=5 event=`init_resource`

## Limitations
- Witness plan is structural only; exact syscall argument synthesis is not implemented.
- witness.syz is a pseudo-syz scaffold for inspection and downstream realization, not a guaranteed runnable syzkaller program.
