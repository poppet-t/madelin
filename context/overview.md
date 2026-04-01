# Overview

## Project purpose

Madelin is an artifact-driven research codebase for turning UAFX-discovered cross-entry UAF candidates into dynamic validation attempts.

## Current product direction

The active direction is a narrow runnable backend for Linux arm64 KVM:

UAFX
→ bridge / witness planner
→ state-aware syzkaller backend
→ candidate-aware crash triage / repro

## Why this exists

UAFX is strong at statically finding cross-entry UAF candidates and reasoning about feasibility, but it does not execute the kernel.
The runtime backend must preserve state, preserve resource chains, steer toward candidate targets, and triage results against the original candidate.

## v1 scope

- Linux
- syzkaller-based execution
- KASAN/KCOV-backed feedback
- arm64 KVM-oriented resource chain
- sequential cross-entry candidates with simple hard-order constraints
- candidate-aware crash triage