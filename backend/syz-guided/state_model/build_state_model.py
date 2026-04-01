#!/usr/bin/env python3
"""Build state_model_v1.json, target_profile.json, and relation_graph_v1.json
from candidate.json + witness_plan.json.

This is the core bridge→backend artifact transformer.  It consumes the
canonical bridge artifacts read-only and produces the three runtime
artifacts that the orchestrator, mutator, seed synthesizer, and triage
modules all depend on.

Usage:
    python build_state_model.py \
        --candidate path/to/candidate.json \
        --witness-plan path/to/witness_plan.json \
        --out-dir path/to/output/
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

# ---------------------------------------------------------------------------
# KVM arm64 resource chain (v1 hard-coded for the supported slice)
# ---------------------------------------------------------------------------

_KVM_RESOURCE_CHAIN = [
    {
        "resource": "fd_kvm",
        "type": "fd",
        "producer_call": "openat$KVM",
        "consumer_calls": ["ioctl$KVM_CREATE_VM"],
    },
    {
        "resource": "fd_vm",
        "type": "fd",
        "producer_call": "ioctl$KVM_CREATE_VM",
        "consumer_calls": ["ioctl$KVM_CREATE_VCPU"],
    },
    {
        "resource": "fd_vcpu",
        "type": "fd",
        "producer_call": "ioctl$KVM_CREATE_VCPU",
        "consumer_calls": [
            "ioctl$KVM_ARM_VCPU_INIT",
            "ioctl$KVM_SET_ONE_REG",
            "ioctl$KVM_GET_ONE_REG",
            "ioctl$KVM_RUN",
        ],
    },
]

# Default v1 score weights — configurable per-campaign later.
_DEFAULT_SCORE_WEIGHTS = {
    "prefix_valid": 0.30,
    "resource_chain": 0.25,
    "phase_progress": 0.20,
    "target_signal": 0.15,
    "order_preserved": 0.10,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: pathlib.Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _write_json(data: dict, path: pathlib.Path) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def _loc_to_slim(loc: dict) -> dict:
    """Extract the slim location triple from a candidate location object."""
    return {
        "function": loc.get("function"),
        "file": loc.get("file"),
        "line": loc.get("line"),
    }


# ---------------------------------------------------------------------------
# Phase classification
# ---------------------------------------------------------------------------

def _classify_phases(candidate: dict) -> dict:
    """Classify template calls into bootstrap / configure / trigger phases.

    For the narrow KVM arm64 slice the classification is deterministic:
      bootstrap = resource-producing calls (openat, CREATE_VM, CREATE_VCPU)
      configure = init/config calls (VCPU_INIT, SET_ONE_REG, GET_ONE_REG)
      trigger   = execution calls (KVM_RUN) + close
    """
    # Collect all template calls across grounded entries.
    all_calls: list[str] = []
    for entry in candidate.get("entries", []):
        if entry.get("support_level") != "grounded":
            continue
        for tmpl in entry.get("syscall_templates", []):
            all_calls.extend(tmpl.get("calls", []))

    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique_calls: list[str] = []
    for c in all_calls:
        canon = c.split("(")[0].strip()
        if canon not in seen:
            seen.add(canon)
            unique_calls.append(canon)

    # Classify by known KVM arm64 patterns.
    bootstrap_kw = {"openat$KVM", "ioctl$KVM_CREATE_VM", "ioctl$KVM_CREATE_VCPU"}
    configure_kw = {"ioctl$KVM_ARM_VCPU_INIT", "ioctl$KVM_SET_ONE_REG", "ioctl$KVM_GET_ONE_REG"}
    trigger_kw = {"ioctl$KVM_RUN", "close$KVM", "close"}

    bootstrap = [c for c in unique_calls if c in bootstrap_kw]
    configure = [c for c in unique_calls if c in configure_kw]
    trigger = [c for c in unique_calls if c in trigger_kw]

    # Any remaining unclassified calls go into trigger as suffix candidates.
    classified = bootstrap_kw | configure_kw | trigger_kw
    for c in unique_calls:
        if c not in classified:
            trigger.append(c)

    return {
        "bootstrap": {
            "calls": bootstrap,
            "description": "Resource-producing calls that create KVM fd chain",
        },
        "configure": {
            "calls": configure,
            "description": "VCPU initialization and register configuration",
        },
        "trigger": {
            "calls": trigger,
            "description": "Execution and teardown calls that may trigger free/use",
        },
    }


# ---------------------------------------------------------------------------
# Sticky calls and prefix
# ---------------------------------------------------------------------------

def _compute_sticky_and_prefix(phases: dict) -> tuple[list[str], int]:
    """Determine sticky calls (must not be removed) and immutable prefix length.

    In v1 the entire bootstrap phase is immutable.  Sticky calls include
    bootstrap + configure calls.
    """
    sticky = phases["bootstrap"]["calls"] + phases["configure"]["calls"]
    prefix_len = len(phases["bootstrap"]["calls"])
    return sticky, prefix_len


def _compute_favored_suffix(candidate: dict) -> list[str]:
    """Identify suffix calls most likely to trigger the free/use region."""
    favored: list[str] = []
    # KVM_RUN is the primary trigger for reaching timer/vcpu teardown paths.
    favored.append("ioctl$KVM_RUN")
    # close triggers resource cleanup / free paths.
    favored.append("close$KVM")
    return favored


# ---------------------------------------------------------------------------
# State model builder
# ---------------------------------------------------------------------------

def build_state_model(
    candidate: dict,
    witness_plan: dict,
    candidate_path: str,
    witness_plan_path: str,
) -> dict:
    """Produce state_model_v1.json from bridge artifacts."""
    ctx = candidate.get("analysis_context", {})
    phases = _classify_phases(candidate)
    sticky, prefix_len = _compute_sticky_and_prefix(phases)

    return {
        "candidate_id": candidate["candidate_id"],
        "schema_version": "state_model/v1",
        "subsystem": ctx.get("subsystem", "unknown"),
        "arch": ctx.get("arch", "unknown"),
        "target_family": ctx.get("target_family", "unknown"),
        "source_artifacts": {
            "candidate_path": candidate_path,
            "witness_plan_path": witness_plan_path,
        },
        "loc0": _loc_to_slim(candidate.get("loc0", {})),
        "loc1": _loc_to_slim(candidate.get("loc1", {})),
        "resource_chain": _KVM_RESOURCE_CHAIN,
        "phases": phases,
        "precedence_edges": witness_plan.get("barriers", []),
        "sticky_calls": sticky,
        "immutable_prefix_len": prefix_len,
        "favored_suffix_calls": _compute_favored_suffix(candidate),
        "score_weights": dict(_DEFAULT_SCORE_WEIGHTS),
    }


# ---------------------------------------------------------------------------
# Target profile builder
# ---------------------------------------------------------------------------

def build_target_profile(candidate: dict) -> dict:
    """Produce target_profile.json from candidate metadata."""
    loc0 = candidate.get("loc0", {})
    loc1 = candidate.get("loc1", {})

    focus_frames = []
    for loc in [loc0, loc1]:
        fn = loc.get("function")
        if fn:
            focus_frames.append(fn)
        for ctx_line in loc.get("context", []):
            if ctx_line and ctx_line not in focus_frames:
                focus_frames.append(ctx_line)

    focus_files = []
    for loc in [loc0, loc1]:
        f = loc.get("file")
        if f and f not in focus_files:
            focus_files.append(f)

    free_use_hints = [
        {"role": "free", **_loc_to_slim(loc0)},
        {"role": "use", **_loc_to_slim(loc1)},
    ]

    preferred_syscalls: list[str] = []
    for entry in candidate.get("entries", []):
        if entry.get("support_level") != "grounded":
            continue
        for tmpl in entry.get("syscall_templates", []):
            for call in tmpl.get("calls", []):
                canon = call.split("(")[0].strip()
                if canon not in preferred_syscalls:
                    preferred_syscalls.append(canon)

    return {
        "candidate_id": candidate["candidate_id"],
        "schema_version": "target_profile/v1",
        "focus_frames": focus_frames,
        "focus_files": focus_files,
        "free_use_hints": free_use_hints,
        "preferred_syscalls": preferred_syscalls,
        "candidate_signal_rules": [
            {
                "rule": "kasan_uaf_in_focus_frame",
                "description": "KASAN use-after-free report with stack frame in focus_frames",
            },
            {
                "rule": "kasan_uaf_in_focus_file",
                "description": "KASAN use-after-free report with source file in focus_files",
            },
            {
                "rule": "free_use_site_match",
                "description": "Crash stack matches loc0 (free) or loc1 (use) function names",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Relation graph builder
# ---------------------------------------------------------------------------

def build_relation_graph(
    candidate: dict,
    witness_plan: dict,
    state_model: dict,
) -> dict:
    """Produce relation_graph_v1.json from candidate + witness plan + state model."""
    nodes: list[dict] = []
    edges: list[dict] = []

    # Resource nodes from the chain.
    for res in state_model.get("resource_chain", []):
        nodes.append({
            "id": f"res:{res['resource']}",
            "type": "resource",
            "phase": "bootstrap",
            "resource": res["resource"],
        })

    # Syscall nodes from phases.
    call_idx = 0
    for phase_name in ["bootstrap", "configure", "trigger"]:
        phase = state_model["phases"][phase_name]
        for call in phase["calls"]:
            node_id = f"call:{call_idx}:{call}"
            nodes.append({
                "id": node_id,
                "type": "syscall",
                "phase": phase_name,
                "call": call,
            })
            call_idx += 1

    # Resource-flow edges.
    for res in state_model.get("resource_chain", []):
        producer_nodes = [n for n in nodes if n["type"] == "syscall" and n.get("call") == res["producer_call"]]
        for pn in producer_nodes:
            edges.append({
                "from": pn["id"],
                "to": f"res:{res['resource']}",
                "type": "resource_flow",
                "resource": res["resource"],
            })
        consumer_calls = res.get("consumer_calls", [])
        for cc in consumer_calls:
            consumer_nodes = [n for n in nodes if n["type"] == "syscall" and n.get("call") == cc]
            for cn in consumer_nodes:
                edges.append({
                    "from": f"res:{res['resource']}",
                    "to": cn["id"],
                    "type": "resource_flow",
                    "resource": res["resource"],
                })

    # Must-precede edges from barriers.
    for barrier in witness_plan.get("barriers", []):
        edges.append({
            "from": f"event:{barrier['before']}",
            "to": f"event:{barrier['after']}",
            "type": "must_precede",
            "reason": barrier.get("reason", ""),
        })

    # Mutation constraints.
    prefix_len = state_model.get("immutable_prefix_len", 0)
    mutation_constraints = [
        {
            "rule": "immutable_prefix",
            "scope": f"calls[0:{prefix_len}]",
            "description": f"First {prefix_len} calls are immutable bootstrap prefix",
        },
        {
            "rule": "suffix_only_mutation",
            "scope": f"calls[{prefix_len}:]",
            "description": "Mutations may only modify calls after the bootstrap prefix",
        },
        {
            "rule": "preserve_resource_chain",
            "scope": "all",
            "description": "Resource producer→consumer flow must not be broken by mutation",
        },
    ]

    return {
        "candidate_id": candidate["candidate_id"],
        "schema_version": "relation_graph/v1",
        "nodes": nodes,
        "edges": edges,
        "mutation_constraints": mutation_constraints,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Build v1 runtime artifacts from bridge artifacts")
    parser.add_argument("--candidate", required=True, help="Path to candidate.json")
    parser.add_argument("--witness-plan", required=True, help="Path to witness_plan.json")
    parser.add_argument("--out-dir", required=True, help="Output directory")
    args = parser.parse_args()

    candidate_path = pathlib.Path(args.candidate)
    plan_path = pathlib.Path(args.witness_plan)
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    candidate = _load_json(candidate_path)
    witness_plan = _load_json(plan_path)

    # Validate inputs have expected schema versions.
    if candidate.get("schema_version") != "candidate/v1":
        print(f"ERROR: candidate schema_version is '{candidate.get('schema_version')}', expected 'candidate/v1'", file=sys.stderr)
        return 1
    if witness_plan.get("schema_version") != "witness_plan/v1":
        print(f"ERROR: witness_plan schema_version is '{witness_plan.get('schema_version')}', expected 'witness_plan/v1'", file=sys.stderr)
        return 1
    if not witness_plan.get("sat"):
        print("ERROR: witness_plan is not SAT — cannot build state model for unsatisfiable plan", file=sys.stderr)
        return 1

    # Build all three artifacts.
    state_model = build_state_model(
        candidate, witness_plan,
        str(candidate_path), str(plan_path),
    )
    target_profile = build_target_profile(candidate)
    relation_graph = build_relation_graph(candidate, witness_plan, state_model)

    # Write outputs.
    _write_json(state_model, out_dir / "state_model_v1.json")
    _write_json(target_profile, out_dir / "target_profile.json")
    _write_json(relation_graph, out_dir / "relation_graph_v1.json")

    # Validate outputs against schemas.
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from schemas import validate as schema_validate

    all_errors: list[str] = []
    for name, artifact in [
        ("state_model_v1", state_model),
        ("target_profile", target_profile),
        ("relation_graph_v1", relation_graph),
    ]:
        errors = schema_validate(artifact, name)
        if errors:
            all_errors.extend([f"{name}: {e}" for e in errors])

    if all_errors:
        print("Schema validation errors:", file=sys.stderr)
        for e in all_errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    print(f"Built state_model_v1.json, target_profile.json, relation_graph_v1.json in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
