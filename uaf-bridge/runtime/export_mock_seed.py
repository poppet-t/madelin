"""Export canonical candidate + witness plan into a MOCK-oriented seed intent JSON."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common.cli import print_cli_error
from common.io import load_json, write_json
from common.schema_validation import validate_candidate, validate_mock_seed, validate_witness_plan

KVM_FOCUS_FAMILIES: list[str] = [
    "KVM_CREATE_VM",
    "KVM_CREATE_VCPU",
    "KVM_RUN",
    "KVM_ARM_VCPU_INIT",
    "KVM_SET_ONE_REG",
    "KVM_GET_ONE_REG",
    "KVM_CREATE_DEVICE",
    "KVM_SET_DEVICE_ATTR",
    "KVM_IRQ_LINE",
]

SEED_VERSION = "mock_seed/v1"


def _selected_template(candidate: dict[str, Any], plan: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    selected = plan.get("execution_hints", {}).get("entry_selection", {})
    selected_template_id = selected.get("template_id") if isinstance(selected, dict) else None

    entries = candidate.get("entries", [])
    if not isinstance(entries, list):
        return None, None

    ordered_entries = sorted(
        [entry for entry in entries if isinstance(entry, dict)],
        key=lambda entry: (
            str(entry.get("support_level", "")),
            str(entry.get("entry_func", "")),
            str(entry.get("entry_kind", "")),
        ),
    )
    for entry in ordered_entries:
        templates = entry.get("syscall_templates", [])
        if not isinstance(templates, list):
            continue
        ordered_templates = sorted(
            [template for template in templates if isinstance(template, dict)],
            key=lambda template: str(template.get("template_id", "")),
        )
        for template in ordered_templates:
            if selected_template_id is not None and template.get("template_id") == selected_template_id:
                return entry, template
    for entry in ordered_entries:
        templates = entry.get("syscall_templates", [])
        if isinstance(templates, list) and templates:
            ordered_templates = sorted(
                [template for template in templates if isinstance(template, dict)],
                key=lambda template: str(template.get("template_id", "")),
            )
            if ordered_templates:
                return entry, ordered_templates[0]
    return None, None


def _entry_confidence(entry: dict[str, Any]) -> str:
    support_level = entry.get("support_level")
    if support_level in {"grounded", "heuristic"}:
        return str(support_level)
    return "unknown"


def _normalize_entries(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    entries = candidate.get("entries", [])
    if not isinstance(entries, list):
        return []
    normalized: list[dict[str, Any]] = []
    for entry in sorted(
        [entry for entry in entries if isinstance(entry, dict)],
        key=lambda item: (str(item.get("entry_func", "")), str(item.get("entry_kind", ""))),
    ):
        templates = entry.get("syscall_templates", [])
        template_ids = []
        if isinstance(templates, list):
            template_ids = sorted(
                [template.get("template_id") for template in templates if isinstance(template, dict) and isinstance(template.get("template_id"), str)]
            )
        notes = [f"mapping_source={entry.get('grounded', {}).get('mapping_source')}"] if entry.get("grounded") else []
        if entry.get("heuristic"):
            notes.append(f"heuristic_mapping_source={entry.get('heuristic', {}).get('mapping_source')}")
        notes.extend([str(reason) for reason in entry.get("unsupported_reasons", []) if isinstance(reason, str)])
        normalized.append(
            {
                "entry_func": entry.get("entry_func"),
                "entry_kind": entry.get("entry_kind"),
                "confidence": _entry_confidence(entry),
                "supported": bool(entry.get("supported", False)),
                "support_level": entry.get("support_level"),
                "template_ids": template_ids,
                "notes": notes,
            }
        )
    return normalized


def _family_from_call(call: str) -> str | None:
    families = [
        "KVM_CREATE_VM",
        "KVM_CREATE_VCPU",
        "KVM_RUN",
        "KVM_ARM_VCPU_INIT",
        "KVM_SET_ONE_REG",
        "KVM_GET_ONE_REG",
        "KVM_CREATE_DEVICE",
        "KVM_SET_DEVICE_ATTR",
        "KVM_IRQ_LINE",
        "openat$KVM",
    ]
    for family in families:
        if family in call:
            return family
    return None


def _resource_effect_from_call(call: str) -> str | None:
    if "openat$KVM" in call:
        return "fd_kvm"
    if "KVM_CREATE_VM" in call:
        return "fd_vm"
    if "KVM_CREATE_VCPU" in call:
        return "fd_vcpu"
    if "KVM_CREATE_DEVICE" in call:
        return "fd_device"
    return None


def _sequence_step(call: str, stage: str, grounding: str) -> dict[str, Any]:
    return {
        "family": _family_from_call(call),
        "grounding": grounding,
        "kind": "syscall",
        "resource_effect": _resource_effect_from_call(call),
        "stage": stage,
        "text": call,
    }


def _split_template_calls(template: dict[str, Any], flow: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    calls = template.get("calls", [])
    if not isinstance(calls, list):
        return [], []
    setup, trigger = [], []
    for idx, call in enumerate([call for call in calls if isinstance(call, str)]):
        step = _sequence_step(call, "setup", "grounded")
        is_setup = idx < 3 or ("CREATE_" in call) or ("openat$KVM" in call)
        if flow == "Con" and "KVM_RUN" in call:
            is_setup = False
        if is_setup:
            setup.append(step)
        else:
            trigger.append({**step, "stage": "trigger"})
    if not trigger and setup:
        trigger = [{**setup[-1], "stage": "trigger"}]
    return setup, trigger


def _extra_kvm_trigger_steps(entry_func: str, flow: str) -> list[dict[str, Any]]:
    heuristics: list[str] = []
    if "vcpu" in entry_func:
        heuristics.extend([
            "ioctl$KVM_ARM_VCPU_INIT(fd_vcpu, KVM_ARM_VCPU_INIT, &init)",
            "ioctl$KVM_RUN(fd_vcpu, KVM_RUN, 0)",
        ])
    if "reg" in entry_func:
        heuristics.extend([
            "ioctl$KVM_SET_ONE_REG(fd_vcpu, KVM_SET_ONE_REG, &one_reg)",
            "ioctl$KVM_GET_ONE_REG(fd_vcpu, KVM_GET_ONE_REG, &one_reg)",
        ])
    if "device" in entry_func or "vgic" in entry_func:
        heuristics.extend([
            "ioctl$KVM_CREATE_DEVICE(fd_vm, KVM_CREATE_DEVICE, &dev)",
            "ioctl$KVM_SET_DEVICE_ATTR(fd_device, KVM_SET_DEVICE_ATTR, &attr)",
        ])
    if not heuristics and flow == "Con":
        heuristics.extend([
            "ioctl$KVM_ARM_VCPU_INIT(fd_vcpu, KVM_ARM_VCPU_INIT, &init)",
            "ioctl$KVM_RUN(fd_vcpu, KVM_RUN, 0)",
        ])
    return [_sequence_step(call, "trigger", "heuristic") for call in heuristics]


def _resource_dependencies(candidate: dict[str, Any], template: dict[str, Any]) -> list[str]:
    resources = template.get("required_resources", []) if isinstance(template, dict) else []
    normalized = [str(resource) for resource in resources if isinstance(resource, str)]
    area = candidate.get("analysis_context", {}).get("kernel_area")
    if area == "arch/arm64/kvm":
        normalized = list(dict.fromkeys(["/dev/kvm", *normalized]))
    return normalized


def _ordered_steps_with_threads(plan: dict[str, Any]) -> list[dict[str, Any]]:
    thread_map: dict[tuple[int, int, str], int] = {}
    threads = plan.get("threads", [])
    if isinstance(threads, list):
        for thread in threads:
            if not isinstance(thread, dict):
                continue
            thread_id = thread.get("thread_id")
            steps = thread.get("steps", [])
            if not isinstance(thread_id, int) or not isinstance(steps, list):
                continue
            for step in steps:
                if not isinstance(step, dict):
                    continue
                key = (int(step.get("step_index", -1)), int(step.get("timestamp", -1)), str(step.get("event")))
                thread_map[key] = thread_id

    ordered = []
    for step in plan.get("ordered_steps", []):
        if not isinstance(step, dict):
            continue
        key = (int(step.get("step_index", -1)), int(step.get("timestamp", -1)), str(step.get("event")))
        ordered.append(
            {
                "event": step.get("event"),
                "step_index": step.get("step_index"),
                "thread_id": thread_map.get(key, 0),
                "timestamp": step.get("timestamp"),
            }
        )
    return ordered


def _predicates(candidate: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    predicate_items = []
    seen: set[tuple[str, str]] = set()
    for source_list in (
        plan.get("predicates", []),
        candidate.get("constraints", {}).get("predicates", []),
    ):
        if not isinstance(source_list, list):
            continue
        for predicate in source_list:
            if not isinstance(predicate, dict):
                continue
            name = predicate.get("name")
            must_hold_at = predicate.get("must_hold_at")
            scope = predicate.get("scope")
            if not (isinstance(name, str) and isinstance(must_hold_at, str)):
                continue
            key = (name, must_hold_at)
            if key in seen:
                continue
            seen.add(key)
            predicate_items.append(
                {
                    "grounding": scope if scope in {"grounded", "heuristic"} else "unknown",
                    "must_hold_at": must_hold_at,
                    "name": name,
                }
            )
    return sorted(predicate_items, key=lambda item: (item["name"], item["must_hold_at"], item["grounding"]))


def _focus_syscall_families(setup_sequence: list[dict[str, Any]], trigger_sequence: list[dict[str, Any]]) -> list[str]:
    families = [step.get("family") for step in [*setup_sequence, *trigger_sequence] if isinstance(step.get("family"), str)]
    families.extend(KVM_FOCUS_FAMILIES)
    return list(dict.fromkeys(families))


def export_mock_seed(candidate: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    validate_candidate(candidate)
    validate_witness_plan(plan)
    if candidate.get("candidate_id") != plan.get("candidate_id"):
        raise ValueError("candidate_id mismatch between candidate and witness plan")
    if not plan.get("sat", False):
        raise ValueError("witness plan is UNSAT; cannot export MOCK seed")

    analysis_context = candidate.get("analysis_context", {})
    entry, template = _selected_template(candidate, plan)
    selected_entry_func = entry.get("entry_func") if isinstance(entry, dict) else None
    selected_entry_kind = entry.get("entry_kind") if isinstance(entry, dict) else None
    selected_template_id = template.get("template_id") if isinstance(template, dict) else None
    selected_confidence = _entry_confidence(entry) if isinstance(entry, dict) else "unknown"

    setup_sequence, trigger_sequence = _split_template_calls(template or {}, candidate.get("flow", "Unknown"))
    trigger_sequence.extend(_extra_kvm_trigger_steps(str(selected_entry_func or ""), candidate.get("flow", "Unknown")))

    ordered_steps = _ordered_steps_with_threads(plan)
    resource_dependencies = _resource_dependencies(candidate, template or {})
    focus_syscall_families = _focus_syscall_families(setup_sequence, trigger_sequence)
    ordering = [
        {"after": edge["after"], "before": edge["before"], "reason": edge["reason"]}
        for edge in plan.get("barriers", [])
        if isinstance(edge, dict)
    ]
    predicates = _predicates(candidate, plan)
    preserve_prefix_len = len(setup_sequence)
    thread_counts = []
    for thread in plan.get("threads", []):
        if isinstance(thread, dict) and isinstance(thread.get("thread_id"), int):
            steps = thread.get("steps", [])
            thread_counts.append({"thread_id": thread["thread_id"], "step_count": len(steps) if isinstance(steps, list) else 0})
    thread_counts = sorted(thread_counts, key=lambda item: item["thread_id"])

    seed = {
        "abstract_steps": [str(event) for event in candidate.get("constraints", {}).get("events", []) if isinstance(event, str)],
        "arch": analysis_context.get("arch", "arm64"),
        "candidate_id": candidate["candidate_id"],
        "confidence": {
            "mapping_confidence": candidate.get("status", {}).get("mapping_confidence", "unknown"),
            "ready_for_smt": bool(candidate.get("status", {}).get("ready_for_smt", False)),
            "supported": bool(candidate.get("status", {}).get("supported", False)),
            "unsupported_reasons": [
                str(reason) for reason in candidate.get("status", {}).get("unsupported_reasons", []) if isinstance(reason, str)
            ],
        },
        "debug": {
            "loc0": candidate.get("loc0", {}),
            "loc1": candidate.get("loc1", {}),
            "notes": [
                "Structural seed intent only: preserves setup chain, ordering, predicates, and concurrency hints.",
                "Exact KVM argument synthesis remains intentionally out of scope for mock_seed/v1.",
            ],
            "same_object": candidate.get("constraints", {}).get("same_object"),
            "selected_entry_func": selected_entry_func,
            "selected_entry_kind": selected_entry_kind,
            "selected_template_id": selected_template_id,
        },
        "entries": _normalize_entries(candidate),
        "flow": candidate.get("flow", "Unknown"),
        "focus_syscall_families": focus_syscall_families,
        "mutation_hints": {
            "focus_syscall_families": focus_syscall_families,
            "keep_ordering_edges": [f"{edge['before']}->{edge['after']}" for edge in ordering],
            "mutate_near_steps": ["fetch", "use"] if candidate.get("flow") == "Con" else ["use"],
            "prefer_collide": candidate.get("flow") == "Con",
            "prefer_two_thread_schedule": plan.get("execution_hints", {}).get("min_threads", 1) >= 2,
            "preserve_prefix_len": preserve_prefix_len,
            "stable_prefix_resources": resource_dependencies,
        },
        "ordered_steps": ordered_steps,
        "ordering": ordering,
        "predicates": predicates,
        "resource_dependencies": resource_dependencies,
        "seed_version": SEED_VERSION,
        "setup_sequence": setup_sequence,
        "source": {
            "normalizer": candidate.get("provenance", {}).get("normalizer"),
            "producer": "uaf-bridge",
            "uafx_warning_id": candidate.get("provenance", {}).get("warning_id"),
            "witness_plan_status": plan.get("status"),
        },
        "subsystem": analysis_context.get("subsystem", "kvm"),
        "target": "linux",
        "thread_hints": {
            "prefer_collide": candidate.get("flow") == "Con",
            "schedule_style": "two-thread-collision" if plan.get("execution_hints", {}).get("min_threads", 1) >= 2 else "single-thread",
            "thread_step_counts": thread_counts,
        },
        "threads": max(int(plan.get("execution_hints", {}).get("min_threads", 1)), 1),
        "trigger_sequence": trigger_sequence,
    }
    if seed["subsystem"] == "kvm" and not any(predicate["name"] == "kvm_fd_ready" for predicate in predicates):
        seed["predicates"].insert(0, {"grounding": selected_confidence, "must_hold_at": "init_resource", "name": "kvm_fd_ready"})
    validate_mock_seed(seed)
    return seed


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export candidate + witness plan into mock_seed.json")
    parser.add_argument("--candidate", required=True, help="Path to candidate.json")
    parser.add_argument("--plan", required=True, help="Path to witness_plan.json")
    parser.add_argument("--output", required=True, help="Path to output mock_seed.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    candidate_id: str | None = None
    try:
        candidate = load_json(Path(args.candidate))
        candidate_id = candidate.get("candidate_id") if isinstance(candidate.get("candidate_id"), str) else None
        plan = load_json(Path(args.plan))
        seed = export_mock_seed(candidate, plan)
        write_json(Path(args.output), seed)
    except Exception as exc:
        return print_cli_error("export_mock_seed", exc, candidate_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
