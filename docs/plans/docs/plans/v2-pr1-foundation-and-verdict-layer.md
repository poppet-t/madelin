# PR1 — Foundation Enforcement and Verdict Layer

## Goal
Implement the first measurable verifier slice:
1. make MOCK respect bridge-emitted structural intent
2. add a verdict layer that can classify crashes against a candidate
3. wire verdict generation into the existing seeded fuzz workflow

## Why now
Without structural preservation, the current runtime throws away bridge intent too quickly.
Without verdicts, later improvements cannot be measured against candidate relevance.

## Current bottleneck
The system currently produces:
- crash / no-crash
but not:
- matched crash
- unrelated crash
- reached path without crash
- setup failed
- timing inconclusive
- path infeasible

Also, bridge-emitted prefix/order hints are not enforced in mutation.

## Scope
Included:
- enforce `preserve_prefix_len`
- enforce `keep_ordering_edges`
- add `mock/verdict/parse_crash.py`
- add `mock/verdict/match_candidate.py`
- add `mock/verdict/emit_verdict.py`
- wire verdict generation into `mock/scripts/run_kvm_seed_fuzz.sh`
- add tests for parser/matcher/emitter

Excluded:
- runnable witness execution
- micro-harness generation
- top-level orchestrator
- coverage oracle beyond simple function-name matching
- full path infeasibility proof

## Assumptions
- KASAN-style crash logs are available or can be collected from current fuzz output
- candidate data already contains enough location/function metadata for a first matcher
- initial matching can be stack-based and heuristic
- `PATH_INFEASIBLE` may remain conservative or deferred if evidence is weak

## Impacted files/modules
Rust:
- `mock/healer_core/src/bridge_bias.rs`
- `mock/healer_core/src/mutation/seq.rs`
- other nearby mutation files if needed for ordering enforcement

Python:
- `mock/verdict/__init__.py`
- `mock/verdict/parse_crash.py`
- `mock/verdict/match_candidate.py`
- `mock/verdict/emit_verdict.py`

Scripts:
- `mock/scripts/run_kvm_seed_fuzz.sh`

Tests/docs:
- `mock/tests/test_crash_parser.py`
- `mock/tests/test_crash_matcher.py`
- `mock/tests/test_verdict_emitter.py`
- update `mock/README.md` if needed

## Risks
- KASAN format variation may require tolerant parsing
- exact free/use frame matching may be noisy at first
- mutation enforcement may be incomplete if all mutation sites are not covered
- `PATH_INFEASIBLE` may be too strong for PR1 and may need to be downgraded or omitted

## Implementation order
1. Enforce prefix preservation in mutation
2. Enforce ordering-edge protection in mutation
3. Add KASAN crash parser
4. Add candidate matcher
5. Add verdict emitter
6. Wire into seeded fuzz post-run
7. Add tests and documentation

## Verification plan
- `cd mock && cargo test -p healer_core`
- `cd mock && PYTHONPATH=. python3 -m unittest tests/test_crash_parser.py tests/test_crash_matcher.py tests/test_verdict_emitter.py`
- `cd mock && bash scripts/prepare_kvm_seed.sh`
- `cd mock && bash scripts/run_kvm_seed_fuzz.sh --dry-run <disk> <ssh_key> <kernel>`
- if real crash logs exist, run parser/matcher against them manually

## Rollback / fallback notes
- verdict generation should be additive; if parsing fails, emit a conservative verdict or skip with explicit reason
- mutation guards should be minimal and reversible
- do not block existing fuzz flow on verdict-layer errors unless explicitly requested

## Definition of done
- mutation respects bridge prefix/order constraints in tested paths
- `verdict.json` is emitted after seeded fuzz runs
- parser/matcher/emitter tests exist and pass
- remaining heuristic parts are stated clearly

## Exact next step for Codex
Implement PR1 only. Do not start witness or harness work.

## Allowed edit scope
- `mock/healer_core/src/bridge_bias.rs`
- `mock/healer_core/src/mutation/*`
- `mock/verdict/*`
- `mock/scripts/run_kvm_seed_fuzz.sh`
- `mock/tests/*`
- `mock/README.md`

## Must remain unchanged
- 3-layer repo architecture
- bridge artifact schemas unless strictly necessary
- existing seeded fuzz startup path semantics