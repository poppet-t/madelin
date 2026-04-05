#!/usr/bin/env python3
"""Build state_model_v1.json, target_profile.json, and relation_graph_v1.json
from candidate.json + witness_plan.json.

This is the core bridge→backend artifact transformer. It consumes the
canonical bridge artifacts read-only and produces the three runtime
artifacts that the orchestrator, mutator, seed synthesizer, and triage
modules all depend on.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pack_registry import resolve_target_manifest

_DEFAULT_SCORE_WEIGHTS = {
    "prefix_valid": 0.30,
    "resource_chain": 0.25,
    "phase_progress": 0.20,
    "target_signal": 0.15,
    "order_preserved": 0.10,
}


def _load_json(path: pathlib.Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _write_json(data: dict, path: pathlib.Path) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def _loc_to_slim(loc: dict) -> dict:
    return {
        "function": loc.get("function"),
        "file": loc.get("file"),
        "line": loc.get("line"),
    }


def _canon_call(call: str) -> str:
    return call.split("(", 1)[0].strip()


def _select_representative_template(candidate: dict, witness_plan: dict) -> dict[str, Any] | None:
    selection = witness_plan.get("execution_hints", {}).get("entry_selection", {})
    selected_entry_func = selection.get("entry_func") if isinstance(selection, dict) else None
    selected_template_id = selection.get("template_id") if isinstance(selection, dict) else None

    entries = candidate.get("entries", [])
    if not isinstance(entries, list):
        return None

    ordered_entries = sorted(
        [entry for entry in entries if isinstance(entry, dict)],
        key=lambda entry: (
            str(entry.get("support_level", "")),
            str(entry.get("entry_func", "")),
            str(entry.get("entry_kind", "")),
        ),
    )

    if isinstance(selected_entry_func, str) and isinstance(selected_template_id, str):
        for entry in ordered_entries:
            if entry.get("entry_func") != selected_entry_func:
                continue
            for template in entry.get("syscall_templates", []):
                if isinstance(template, dict) and template.get("template_id") == selected_template_id:
                    return template

    for entry in ordered_entries:
        templates = entry.get("syscall_templates", [])
        if not isinstance(templates, list):
            continue
        ordered_templates = sorted(
            [template for template in templates if isinstance(template, dict)],
            key=lambda template: str(template.get("template_id", "")),
        )
        if ordered_templates:
            return ordered_templates[0]
    return None


def _collect_unique_calls(candidate: dict, witness_plan: dict) -> list[str]:
    template = _select_representative_template(candidate, witness_plan)
    if not isinstance(template, dict):
        return []
    raw_calls = template.get("calls", [])
    seen: set[str] = set()
    unique: list[str] = []
    for call in raw_calls:
        if not isinstance(call, str):
            continue
        canon = _canon_call(call)
        if canon in seen:
            continue
        seen.add(canon)
        unique.append(canon)
    return unique


def _classify_phases(unique_calls: list[str], manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    phase_calls = manifest.get("phase_calls", {}) if isinstance(manifest.get("phase_calls"), dict) else {}
    bootstrap_set = {str(call) for call in phase_calls.get("bootstrap", []) if isinstance(call, str)}
    configure_set = {str(call) for call in phase_calls.get("configure", []) if isinstance(call, str)}
    trigger_set = {str(call) for call in phase_calls.get("trigger", []) if isinstance(call, str)}

    bootstrap = [call for call in unique_calls if call in bootstrap_set]
    configure = [call for call in unique_calls if call in configure_set]
    trigger = [call for call in unique_calls if call in trigger_set]

    classified = bootstrap_set | configure_set | trigger_set
    for call in unique_calls:
        if call not in classified:
            if not bootstrap:
                bootstrap.append(call)
            else:
                trigger.append(call)

    return {
        "bootstrap": {
            "calls": bootstrap,
            "description": f"{manifest['pack']}: bootstrap/resource-producing prefix",
        },
        "configure": {
            "calls": configure,
            "description": f"{manifest['pack']}: configuration/register phase",
        },
        "trigger": {
            "calls": trigger,
            "description": f"{manifest['pack']}: trigger/teardown phase",
        },
    }


def _resource_chain(manifest: dict[str, Any], unique_calls: list[str]) -> list[dict[str, Any]]:
    call_set = set(unique_calls)
    chain: list[dict[str, Any]] = []
    for resource in manifest.get("resource_chain", []):
        if not isinstance(resource, dict):
            continue
        producer = resource.get("producer_call")
        if not isinstance(producer, str) or producer not in call_set:
            continue
        consumers = resource.get("consumer_calls", [])
        filtered_consumers = [consumer for consumer in consumers if isinstance(consumer, str) and consumer in call_set]
        chain.append(
            {
                "resource": resource.get("resource"),
                "type": resource.get("type", "fd"),
                "producer_call": producer,
                "consumer_calls": filtered_consumers,
            }
        )
    return chain


def _compute_sticky_and_prefix(phases: dict[str, dict[str, Any]]) -> tuple[list[str], int]:
    sticky = phases["bootstrap"]["calls"] + phases["configure"]["calls"]
    prefix_len = len(phases["bootstrap"]["calls"])
    return sticky, prefix_len


def _favored_suffix_calls(manifest: dict[str, Any], unique_calls: list[str], phases: dict[str, dict[str, Any]]) -> list[str]:
    favored = [call for call in manifest.get("favored_suffix_calls", []) if isinstance(call, str) and call in unique_calls]
    if favored:
        return list(dict.fromkeys(favored))
    return list(dict.fromkeys(phases["trigger"]["calls"]))


def _candidate_manifest(candidate: dict) -> dict[str, Any]:
    ctx = candidate.get("analysis_context", {}) if isinstance(candidate.get("analysis_context"), dict) else {}
    return resolve_target_manifest(
        kernel_area=ctx.get("kernel_area") if isinstance(ctx.get("kernel_area"), str) else None,
        subsystem=ctx.get("subsystem") if isinstance(ctx.get("subsystem"), str) else None,
        target_family=ctx.get("target_family") if isinstance(ctx.get("target_family"), str) else None,
    )


def build_state_model(
    candidate: dict,
    witness_plan: dict,
    candidate_path: str,
    witness_plan_path: str,
) -> dict:
    ctx = candidate.get("analysis_context", {})
    manifest = _candidate_manifest(candidate)
    unique_calls = _collect_unique_calls(candidate, witness_plan)
    phases = _classify_phases(unique_calls, manifest)
    sticky, prefix_len = _compute_sticky_and_prefix(phases)

    return {
        "candidate_id": candidate["candidate_id"],
        "schema_version": "state_model/v1",
        "subsystem": ctx.get("subsystem", manifest.get("subsystem", "unknown")),
        "arch": ctx.get("arch", manifest.get("arch", "unknown")),
        "target_family": ctx.get("target_family", "unknown"),
        "source_artifacts": {
            "candidate_path": candidate_path,
            "witness_plan_path": witness_plan_path,
        },
        "loc0": _loc_to_slim(candidate.get("loc0", {})),
        "loc1": _loc_to_slim(candidate.get("loc1", {})),
        "resource_chain": _resource_chain(manifest, unique_calls),
        "phases": phases,
        "precedence_edges": witness_plan.get("barriers", []),
        "sticky_calls": sticky,
        "immutable_prefix_len": prefix_len,
        "favored_suffix_calls": _favored_suffix_calls(manifest, unique_calls, phases),
        "score_weights": dict(_DEFAULT_SCORE_WEIGHTS),
    }


def build_target_profile(candidate: dict) -> dict:
    manifest = _candidate_manifest(candidate)
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
    template = _select_representative_template(candidate, {"execution_hints": {"entry_selection": {}}})
    if isinstance(template, dict):
        for call in template.get("calls", []):
            if isinstance(call, str):
                canon = _canon_call(call)
                if canon not in preferred_syscalls:
                    preferred_syscalls.append(canon)

    candidate_signal_rules = []
    for index, description in enumerate(manifest.get("triage_signal_rules", []), start=1):
        if isinstance(description, str):
            candidate_signal_rules.append({"rule": f"{manifest['pack']}_signal_{index}", "description": description})
    if not candidate_signal_rules:
        candidate_signal_rules = [
            {"rule": "focus_frame_hit", "description": "Crash stack includes a focus frame."},
            {"rule": "focus_file_hit", "description": "Crash stack includes a focus file."},
        ]

    return {
        "candidate_id": candidate["candidate_id"],
        "schema_version": "target_profile/v1",
        "focus_frames": focus_frames,
        "focus_files": focus_files,
        "free_use_hints": free_use_hints,
        "preferred_syscalls": preferred_syscalls,
        "candidate_signal_rules": candidate_signal_rules,
    }


def build_relation_graph(
    candidate: dict,
    witness_plan: dict,
    state_model: dict,
) -> dict:
    nodes: list[dict] = []
    edges: list[dict] = []

    for res in state_model.get("resource_chain", []):
        nodes.append({
            "id": f"res:{res['resource']}",
            "type": "resource",
            "phase": "bootstrap",
            "resource": res["resource"],
        })

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

    for res in state_model.get("resource_chain", []):
        producer_nodes = [n for n in nodes if n["type"] == "syscall" and n.get("call") == res["producer_call"]]
        for pn in producer_nodes:
            edges.append({
                "from": pn["id"],
                "to": f"res:{res['resource']}",
                "type": "resource_flow",
                "resource": res["resource"],
            })
        for consumer_call in res.get("consumer_calls", []):
            consumer_nodes = [n for n in nodes if n["type"] == "syscall" and n.get("call") == consumer_call]
            for cn in consumer_nodes:
                edges.append({
                    "from": f"res:{res['resource']}",
                    "to": cn["id"],
                    "type": "resource_flow",
                    "resource": res["resource"],
                })

    for barrier in witness_plan.get("barriers", []):
        edges.append({
            "from": f"event:{barrier['before']}",
            "to": f"event:{barrier['after']}",
            "type": "must_precede",
            "reason": barrier.get("reason", ""),
        })

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

    if candidate.get("schema_version") != "candidate/v1":
        print(f"ERROR: candidate schema_version is '{candidate.get('schema_version')}', expected 'candidate/v1'", file=sys.stderr)
        return 1
    if witness_plan.get("schema_version") != "witness_plan/v1":
        print(f"ERROR: witness_plan schema_version is '{witness_plan.get('schema_version')}', expected 'witness_plan/v1'", file=sys.stderr)
        return 1
    if not witness_plan.get("sat"):
        print("ERROR: witness_plan is not SAT — cannot build state model for unsatisfiable plan", file=sys.stderr)
        return 1

    state_model = build_state_model(candidate, witness_plan, str(candidate_path), str(plan_path))
    target_profile = build_target_profile(candidate)
    relation_graph = build_relation_graph(candidate, witness_plan, state_model)

    _write_json(state_model, out_dir / "state_model_v1.json")
    _write_json(target_profile, out_dir / "target_profile.json")
    _write_json(relation_graph, out_dir / "relation_graph_v1.json")

    from schemas import validate as schema_validate

    all_errors: list[str] = []
    for name, artifact in [
        ("state_model_v1", state_model),
        ("target_profile", target_profile),
        ("relation_graph_v1", relation_graph),
    ]:
        errors = schema_validate(artifact, name)
        if errors:
            all_errors.extend([f"{name}: {error}" for error in errors])

    if all_errors:
        print("Schema validation errors:", file=sys.stderr)
        for error in all_errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    print(f"Built state_model_v1.json, target_profile.json, relation_graph_v1.json in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
