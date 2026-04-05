# PRD — Static-to-Dynamic Witness Bridge for Cross-Entry Kernel UAF Detection

## 1. Product name
UAF Witness Bridge

## 2. Summary
Build a research prototype that links a static cross-entry lifetime-bug analysis pipeline to a dynamic kernel validation workflow using Z3 as a witness-synthesis bridge.

The system ingests static candidates extracted from LLVM-based analysis, normalizes them into a canonical candidate schema, encodes feasibility constraints into Z3, solves for a runnable witness schedule, and emits a plan-aware syscall prefix for a syzkaller-style executor/fuzzer to realize and validate.

The practical execution environment target is **hardware-light arm64**: ordinary arm64 Linux VMs with no nested virtualization and no special passthrough hardware. Subsystem scope is managed through **target packs** (KVM is one pack; other packs cover software-reachable user/kernel interfaces such as io_uring, netlink/netfilter, eBPF, and mount/FUSE).

The product goal is not generic fuzzing. The goal is traceable end-to-end validation:

static warning -> normalized candidate -> SMT witness -> runnable syscall plan -> runtime crash or rejection

## 3. Problem statement
Static analysis finds many plausible cross-entry UAF candidates but does not produce a concrete, runnable trigger.
Dynamic fuzzing can find concrete crashes but lacks guidance about which sequence, ordering, and concurrency structure are most likely to realize a given static candidate.

There is a missing bridge between:
- static relational evidence
- concrete executable witness generation

This system fills that gap.

## 4. Goals
1. Parse one static warning into a stable machine-readable candidate format.
2. Map candidate entrypoints into user-triggerable syscall templates.
3. Encode ordering / alias / resource / concurrency constraints into Z3.
4. Extract a SAT model as a witness plan.
5. Emit a runnable witness skeleton for a plan-aware dynamic executor.
6. Validate whether the witness can be realized and whether it produces a crash consistent with the original candidate.
7. Package proof artifacts for research reporting.

## 5. Non-goals
- Full automatic argument synthesis for all drivers.
- Universal support for all kernel subsystems in v1.
- Modifying Z3 internals.
- Replacing syzkaller’s mutation engine.
- Proving semantic equivalence between static and dynamic traces in full generality.

## 6. Users
Primary user:
- the researcher building and evaluating the static+dynamic cross-entry UAF system

Secondary users:
- future contributors extending driver coverage, entry mapping, and runtime realization
- paper reviewers or collaborators who need reproducible evidence bundles

## 7. Primary use case
Given a static warning containing free/use sites, path contexts, and cross-entry relations, the system should:
1. extract a normalized candidate
2. infer one or more syscall trigger templates
3. synthesize a feasible schedule with Z3
4. emit a witness program prefix
5. run dynamic realization
6. return SAT+crash, SAT+no-crash-yet, or UNSAT

## 8. Success criteria
### v0 success
- One real warning can be converted into `candidate.json`
- One hand-mapped entry template can be solved by Z3
- One witness plan can be emitted as JSON

### v1 success
- One witness plan can be converted into a syz-style prefix
- One plan-aware execution path runs in QEMU
- Result bundles are generated consistently

### research success
- The pipeline reduces brute-force search over candidate realizations
- The system produces reproducible witness artifacts for at least one scoped driver family

## 9. Product scope

### In scope for v1
- LLVM/bitcode-based static candidate intake
- Candidate normalization
- Manual or semi-manual entry-to-syscall mapping
- Z3-based schedule feasibility solving
- Witness-plan emission
- Syz-style prefix generation
- Plan-aware runtime mode
- Proof bundle generation
- Target-pack model for scoping supported subsystem families without changing artifact contracts

### Out of scope for v1
- Generalized argument/value solving in SMT
- Full driver environment inference
- Automatic support for every subsystem
- Large-scale campaign orchestration

### Initial target packs (v1 pivot scope)
The v1 pivot focuses on software-reachable subsystems that can be exercised from standard userspace in a VM:
- io_uring
- netlink / netfilter / control-plane families
- eBPF
- mount API / FUSE
- optional second-wave: ublk

## 10. System design overview

### Stage A — Static intake
Input:
- warning JSON or warning-like extracted record from static analysis

Output:
- canonical `candidate.json`

Responsibilities:
- extract free/use sites
- extract entry contexts
- classify flow as sequential or concurrent
- record available ordering and predicate constraints
- store raw provenance

### Stage B — Mapping
Input:
- `candidate.json`

Output:
- enriched `candidate.json` with entry templates

Responsibilities:
- classify entrypoints
- map entrypoints to syscall skeletons
- rank mappings by triggerability

### Stage C — SMT witness synthesis
Input:
- enriched candidate

Output:
- `witness_plan.json`

Responsibilities:
- create symbolic event variables
- encode ordering, thread, alias, lock, and resource constraints
- solve SAT/UNSAT
- extract a concrete model

### Stage D — Dynamic realization
Input:
- `witness_plan.json`

Output:
- `witness.syz`, run logs, crash artifacts

Responsibilities:
- instantiate a hard prefix
- allow a soft mutation/repair tail
- run under instrumented VM/kernel
- collect crashes and reports

### Stage E — Proof packaging
Input:
- candidate, witness plan, runtime artifacts

Output:
- reproducible artifact bundle

Responsibilities:
- tie runtime result back to original static evidence
- render markdown summary
- store repro and logs

## 11. Functional requirements

### FR-1 Candidate normalization
The system shall ingest a static warning file and produce a canonical `candidate.json`.

Required fields:
- candidate_id
- source metadata
- raw_warning
- loc0
- loc1
- flow
- top_entry_functions
- constraints
- status

### FR-2 Entry classification
The system shall classify supported entry surfaces into a normalized taxonomy suitable for witness planning.

Minimum initial taxonomy:
- file_ioctl
- file_read
- file_write
- sysfs_show
- sysfs_store

Target-pack extensions (may start as hints/templates; must remain explicit about unsupported cases):
- io_uring_setup
- io_uring_enter
- io_uring_register
- netlink_send
- netlink_recv
- bpf_cmd
- mount_api_step
- fuse_control
- poll_wait
- mmap_interaction
- close_teardown
- fd_dup_or_share

### FR-3 Syscall template generation
The system shall emit one or more syscall templates for each supported entry class.

Examples:
- file_ioctl -> openat + ioctl
- file_read -> openat + read
- file_write -> openat + write
- sysfs_show -> openat(path) + read
- sysfs_store -> openat(path) + write

### FR-4 SMT encoding
The system shall encode at minimum:
- event timestamps
- event ordering
- optional thread ids
- resource readiness predicates
- alias equality constraints where available

### FR-5 SAT/UNSAT output
The system shall emit:
- SAT with model and witness plan
- or UNSAT with debug metadata

### FR-6 Witness plan generation
The system shall emit a runtime-friendly plan with:
- ordered steps
- thread grouping
- barrier edges
- predicates
- execution hints

### FR-7 Dynamic prefix generation
The system shall convert a witness plan into a syz-style prefix representation.

### FR-8 Runtime realization
The system shall support a plan-aware runtime mode where:
- prefix steps are fixed
- tail steps may be mutated or repaired
- concurrency hints are honored when possible

### FR-9 Artifact bundle
The system shall package:
- candidate.json
- witness_plan.json
- witness.syz
- runtime logs
- crash report
- proof.md

## 12. Non-functional requirements

### NFR-1 Traceability
Every generated artifact must be linked back to a candidate_id.

### NFR-2 Reproducibility
Given the same candidate and seed inputs, the system should produce deterministic intermediate artifacts up to the dynamic fuzzing stage.

### NFR-3 Debbugability
Intermediate representations must be saved to disk in readable JSON.

### NFR-4 Extensibility
The design must permit:
- new entry mappers
- new constraint families
- new runtime backends

### NFR-5 Isolation
The solver layer must remain a separate module from static extraction and runtime realization.

## 13. Data model

### candidate.json
Core fields:
- candidate_id
- source
- raw_warning
- loc0
- loc1
- flow
- entries[]
- constraints{}
- ranking{}
- status{}

### witness_plan.json
Core fields:
- candidate_id
- sat
- model{}
- threads[]
- barriers[]
- predicates[]
- execution_hints{}
- debug{}

## 14. Initial constraint model

### Hard constraints
- escape < fetch
- free < use
- init < cleanup
- timestamps are distinct where required
- required resources exist before dependent steps

### Optional constraints
- same object / alias equality
- lock order disjunctions
- condition enable/check ordering
- thread lifecycle ordering

## 15. Milestones

### M0 — Environment
- baseline static toolchain available
- Z3 available
- syzkaller/QEMU baseline available

### M1 — Candidate pipeline
- one warning -> one normalized candidate

### M2 — Minimal SMT
- one candidate -> SAT model -> witness plan

### M3 — Prefix emitter
- one witness plan -> one syz-style prefix

### M4 — Runtime integration
- one plan-aware runtime execution path

### M5 — Artifact packaging
- one end-to-end result bundle

## 16. Risks and mitigations

### Risk: entrypoint ambiguity
Mitigation:
- start with manual mapping table
- support only deterministic surfaces first

### Risk: SMT model is satisfiable but runtime realization fails
Mitigation:
- keep SMT focused on structure, not exact values
- let runtime repair/mutate concrete arguments

### Risk: unrelated crashes
Mitigation:
- implement crash matcher against subsystem/function neighborhood
- require prefix execution evidence

### Risk: overcomplicated first implementation
Mitigation:
- v1 supports one narrow driver family and a handful of entry classes

## 17. Open questions
- What exact warning schema will the static side emit first?
- Which scoped driver family will be the first evaluation target?
- How much of the runtime should patch syzkaller versus use an external prefix injector?
- What minimum proof criteria are needed to call a crash “matched” to a candidate?

## 18. Acceptance test for v1
Given one curated static warning from a supported entry surface, the system should:
1. generate `candidate.json`
2. solve and emit `witness_plan.json`
3. emit `witness.syz`
4. execute the prefix in the target VM
5. save logs and a proof bundle
