# Proof Bundle for cand_59fda0076e3243f2

## Summary
- Candidate ID: `cand_59fda0076e3243f2`
- Candidate schema: `candidate/v1`
- Witness plan schema: `witness_plan/v1`
- Solver status: `sat`
- SAT: `True`
- Witness file: `out/uafx_kvm_witness.syz`
- Generated at (UTC): `2026-03-17T16:19:38.890548+00:00`

## Source
- Tool: `uafx-bridge-import`
- Version: `0.1`
- Raw file: `out/uafx_kvm_bridge_export.json`

## Entry Classifications
- `kvm_vcpu_ioctl` -> `file_ioctl` (supported=True, support_level=grounded, unsupported_reasons=[])
- `kvm_vm_ioctl_create_vcpu` -> `file_ioctl` (supported=True, support_level=grounded, unsupported_reasons=[])

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
