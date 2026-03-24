# Overview

## What this repository is for
This repository implements a prototype UAF witness bridge that connects:
1. static warning output
2. normalized candidate extraction
3. SMT-based structural feasibility solving
4. runtime witness or seed emission
5. downstream MOCK-oriented fuzzing handoff

## Current emphasis
The current implementation is intentionally narrow and optimized for:
- stable artifact contracts
- deterministic transforms up to runtime
- explicit unsupported-case handling
- Linux arm64 KVM-oriented entry families and demos

## What success looks like
A successful change:
- preserves cross-stage contracts
- keeps schema drift controlled
- improves witness feasibility or runtime usefulness
- remains reviewable and testable
- does not broaden the system accidentally

## What to avoid
- architecture rewrites during implementation tasks
- silent schema changes
- hidden changes to ordering semantics
- “helpful” generalization that breaks narrow supported paths
- mixing planning, implementation, and review in one uncontrolled pass
