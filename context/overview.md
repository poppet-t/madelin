# Overview

## Project purpose

Madelin is an artifact-driven research codebase for turning UAFX-discovered cross-entry UAF candidates into dynamic validation attempts.

## Current product direction

The active direction is an artifact-driven kernel validation workflow for **hardware-light
arm64 environments** (ordinary arm64 Linux VMs without nested virtualization or special
passthrough hardware), scoped by **target packs**:

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
- target-pack resource chains (KVM is the legacy/initial pack; additional packs cover
  software-reachable subsystems such as io_uring, netlink/netfilter, eBPF, and mount/FUSE)
- sequential cross-entry candidates with simple hard-order constraints
- candidate-aware crash triage
