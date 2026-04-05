"""Emit a runnable narrow-KVM syzkaller witness from candidate and witness plan."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common.cli import print_cli_error
from common.io import load_json, write_text
from common.schema_validation import validate_candidate, validate_witness_plan
from mapping.syz_descriptions import bridge_family_from_template_call, harvest_kvm_descriptions
from mapping.target_registry import resolve_target_manifest


def _unsupported_witness_candidate(reason: str) -> ValueError:
    return ValueError(f"unsupported witness candidate: {reason}")


def _unsupported_witness_template(reason: str) -> ValueError:
    return ValueError(f"unsupported witness template: {reason}")


def _candidate_manifest(candidate: dict[str, Any]) -> dict[str, Any]:
    analysis_context = candidate.get("analysis_context")
    if not isinstance(analysis_context, dict):
        return resolve_target_manifest()
    return resolve_target_manifest(
        kernel_area=analysis_context.get("kernel_area") if isinstance(analysis_context.get("kernel_area"), str) else None,
        subsystem=analysis_context.get("subsystem") if isinstance(analysis_context.get("subsystem"), str) else None,
        target_family=analysis_context.get("target_family") if isinstance(analysis_context.get("target_family"), str) else None,
    )


def select_representative_template(
    candidate: dict[str, Any], plan: dict[str, Any]
) -> tuple[str, str, dict[str, Any]]:
    """Pick a stable representative syscall template from candidate entries."""
    selected = plan.get("execution_hints", {}).get("entry_selection", {})
    selected_template_id = selected.get("template_id") if isinstance(selected, dict) else None

    entries = candidate.get("entries", [])
    if not isinstance(entries, list):
        raise ValueError("candidate.entries must be an array")

    candidates: list[tuple[str, str, dict[str, Any]]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_func = entry.get("entry_func")
        entry_kind = entry.get("entry_kind")
        templates = entry.get("syscall_templates")
        if not (isinstance(entry_func, str) and isinstance(entry_kind, str) and isinstance(templates, list)):
            continue
        for template in templates:
            if isinstance(template, dict):
                candidates.append((entry_func, entry_kind, template))

    if not candidates:
        raise _unsupported_witness_candidate(
            "no syscall template is available in candidate entries for the runnable narrow-KVM subset"
        )

    ordered = sorted(candidates, key=lambda item: (item[0], item[1], str(item[2].get("template_id", ""))))
    for entry_func, entry_kind, template in ordered:
        if template.get("template_id") == selected_template_id:
            return entry_func, entry_kind, template
    return ordered[0]


def ordered_plan_steps_with_threads(plan: dict[str, Any]) -> list[dict[str, int | str]]:
    """Attach thread ids to ordered plan steps using the schedule payload."""
    thread_by_key: dict[tuple[int, int, str], int] = {}
    threads = plan.get("threads", [])
    if not isinstance(threads, list) or not threads:
        raise ValueError("witness plan has no thread schedule")
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
            thread_by_key[key] = thread_id

    ordered_steps = plan.get("ordered_steps", [])
    if not isinstance(ordered_steps, list):
        raise ValueError("witness plan has no ordered steps")

    normalized: list[dict[str, int | str]] = []
    for step in ordered_steps:
        if not isinstance(step, dict):
            continue
        key = (int(step.get("step_index", -1)), int(step.get("timestamp", -1)), str(step.get("event")))
        normalized.append(
            {
                "event": str(step.get("event")),
                "step_index": int(step.get("step_index", -1)),
                "thread_id": thread_by_key.get(key, 0),
                "timestamp": int(step.get("timestamp", -1)),
            }
        )
    if not normalized:
        raise ValueError("witness plan has no ordered steps")
    return normalized


def thread_ids_by_event(plan: dict[str, Any]) -> dict[str, int]:
    """Build a stable event-to-thread mapping for the structural schedule."""
    mapping: dict[str, int] = {}
    for step in ordered_plan_steps_with_threads(plan):
        event = str(step["event"])
        thread_id = int(step["thread_id"])
        existing = mapping.get(event)
        if existing is not None and existing != thread_id:
            raise ValueError(
                f"witness plan assigns event {event} to multiple threads; runnable witness needs a stable event mapping"
            )
        mapping[event] = thread_id
    return mapping


def template_witness_families(template: dict[str, Any]) -> list[str]:
    """Translate template call text into the supported bridge family sequence."""
    calls = template.get("calls", [])
    if not isinstance(calls, list) or not all(isinstance(call, str) for call in calls):
        raise _unsupported_witness_template("template calls must be a string array")

    families: list[str] = []
    for call in calls:
        family = bridge_family_from_template_call(call)
        if family is None:
            raise _unsupported_witness_template(
                f"template call is not part of the runnable narrow-KVM witness subset: {call}"
            )
        families.append(family)
    if not families:
        raise _unsupported_witness_template("representative template has no runnable witness families")
    return families


def _template_call_names(template: dict[str, Any]) -> list[str]:
    calls = template.get("calls", [])
    if not isinstance(calls, list) or not all(isinstance(call, str) for call in calls):
        raise _unsupported_witness_template("template calls must be a string array")

    families: list[str] = []
    for call in calls:
        family = call.split("(", 1)[0].strip()
        if not family:
            raise _unsupported_witness_template(f"template call has no callable family: {call}")
        families.append(family)
    return families


def _generic_event_for_call(family: str, call_index: int, total_calls: int) -> str:
    lowered = family.lower()
    if call_index == 0:
        return "init_resource"
    if any(token in lowered for token in ("register", "config", "attach", "create")):
        return "escape"
    if any(token in lowered for token in ("lookup", "get", "dump", "read", "poll", "mmap", "update")):
        return "fetch"
    if any(token in lowered for token in ("delete", "detach", "release", "free")):
        return "free"
    if any(token in lowered for token in ("close", "umount")):
        return "cleanup" if call_index == total_calls - 1 else "free"
    if any(token in lowered for token in ("enter", "run", "move_mount")):
        return "use"
    return "use" if call_index >= max(total_calls - 2, 1) else "fetch"


def _render_generic_witness(candidate: dict[str, Any], plan: dict[str, Any], manifest: dict[str, Any]) -> str:
    entry_func, entry_kind, template = select_representative_template(candidate, plan)
    template_id = template.get("template_id", "unknown_template")
    required_resources = template.get("required_resources", [])
    if not isinstance(required_resources, list) or not all(isinstance(resource, str) for resource in required_resources):
        raise _unsupported_witness_template("template required_resources must be a string array")

    call_map = manifest.get("syz_call_map", {})
    if not isinstance(call_map, dict):
        raise _unsupported_witness_template(f"target pack '{manifest['pack']}' is missing syz_call_map")

    families = _template_call_names(template)
    unsupported = [family for family in families if family not in call_map]
    if unsupported:
        unsupported_text = ", ".join(sorted(dict.fromkeys(unsupported)))
        raise _unsupported_witness_template(
            f"representative template needs future runnable-witness support: {unsupported_text}"
        )

    plan_steps = ordered_plan_steps_with_threads(plan)
    event_threads = thread_ids_by_event(plan)
    execution_hints = plan.get("execution_hints", {})
    min_threads = int(execution_hints.get("min_threads", 1))
    concurrent = min_threads > 1 or candidate.get("flow") == "Con"

    lines: list[str] = []
    lines.append("# uaf_bridge_witness=runnable")
    lines.append(f"# candidate_id={candidate['candidate_id']}")
    lines.append(f"# candidate_schema_version={candidate['schema_version']}")
    lines.append(f"# witness_plan_schema_version={plan['schema_version']}")
    lines.append(f"# representative_entry_func={entry_func}")
    lines.append(f"# representative_entry_kind={entry_kind}")
    lines.append(f"# representative_template_id={template_id}")
    lines.append("# syzkaller_root=pack-generic")
    lines.append(f"# target_pack={manifest['pack']}")
    lines.append(f"# required_resources={','.join(required_resources) if required_resources else '(none)'}")
    lines.append("# schedule_note=structural_plan_steps_are_preserved_in_comments")
    lines.append("# concrete_order_note=template_order_preserves_target_pack_dependencies")
    lines.append(
        f"# exec_mode threaded={1 if concurrent else 0} collide={1 if concurrent else 0} procs={max(min_threads, 1)}"
    )
    lines.append("")

    for step in plan_steps:
        lines.append(
            "# plan_step "
            f"step_index={step['step_index']} "
            f"event={step['event']} "
            f"thread={step['thread_id']} "
            f"timestamp={step['timestamp']}"
        )

    lines.append("")
    for call_index, family in enumerate(families):
        event = _generic_event_for_call(family, call_index, len(families))
        thread_id = event_threads.get(event, 0)
        lines.append(f"# call_index={call_index} family={family} event={event} thread={thread_id}")
        lines.append(str(call_map[family]))

    return "\n".join(lines) + "\n"


def _format_numeric(value: int) -> str:
    return hex(value) if value >= 0 else str(value)


def _render_struct_arg(struct_name: str, descriptions: dict[str, Any]) -> str:
    constants = descriptions["constants"]
    if struct_name == "kvm_vcpu_init":
        target = _format_numeric(int(constants["KVM_ARM_TARGET_GENERIC_V8"]))
        return f"&AUTO={{{target}, 0x0, [0x0, 0x0, 0x0, 0x0, 0x0, 0x0]}}"
    if struct_name == "kvm_one_reg":
        return "&AUTO={0x0, 0x0}"
    raise ValueError(f"unsupported runnable witness struct default: {struct_name}")


def _render_family_call(
    family: str,
    descriptions: dict[str, Any],
    resource_vars: dict[str, str],
    next_result_index: int,
) -> tuple[str, int]:
    syscall = descriptions["syscalls"][family]
    constants = descriptions["constants"]
    args: list[str]

    if family == "openat$KVM":
        args = [
            _format_numeric(int(constants["AT_FDCWD"])),
            "&AUTO='/dev/kvm\\x00'",
            "0x2",
            "0x0",
        ]
    else:
        input_resource = syscall.get("bridge_input_resource")
        if not isinstance(input_resource, str) or input_resource not in resource_vars:
            raise ValueError(f"missing required witness resource before {family}: {input_resource}")
        constant_name = syscall.get("constant_name")
        if not isinstance(constant_name, str) or constant_name not in constants:
            raise ValueError(f"missing runnable witness constant for {family}: {constant_name}")
        args = [resource_vars[input_resource], _format_numeric(int(constants[constant_name]))]
        if family == "KVM_CREATE_VM":
            args.append("0x0")
        elif family == "KVM_CREATE_VCPU":
            args.append("0x0")
        elif family == "KVM_ARM_VCPU_INIT":
            args.append(_render_struct_arg("kvm_vcpu_init", descriptions))
        elif family in {"KVM_SET_ONE_REG", "KVM_GET_ONE_REG"}:
            args.append(_render_struct_arg("kvm_one_reg", descriptions))
        elif family == "KVM_RUN":
            args.append("0x0")
        else:  # pragma: no cover - guarded by template subset selection
            raise ValueError(f"runnable witness family not yet implemented: {family}")

    line = f"{syscall['syz_name']}({', '.join(args)})"
    output_resource = syscall.get("bridge_output_resource")
    if isinstance(output_resource, str):
        result_var = f"r{next_result_index}"
        line = f"{result_var} = {line}"
        resource_vars[output_resource] = result_var
        next_result_index += 1
    return line, next_result_index


def render_witness(
    candidate: dict[str, Any], plan: dict[str, Any], syz_root: str | Path | None = None
) -> str:
    """Render a runnable witness program with structural schedule metadata."""
    validate_candidate(candidate)
    validate_witness_plan(plan)

    if not plan.get("sat", False):
        raise ValueError("witness plan is UNSAT; cannot emit runnable witness")
    if candidate.get("candidate_id") != plan.get("candidate_id"):
        raise ValueError("candidate_id mismatch between candidate and witness plan")

    manifest = _candidate_manifest(candidate)
    if manifest.get("pack") != "kvm":
        return _render_generic_witness(candidate, plan, manifest)

    entry_func, entry_kind, template = select_representative_template(candidate, plan)
    template_id = template.get("template_id", "unknown_template")
    required_resources = template.get("required_resources", [])
    if not isinstance(required_resources, list) or not all(isinstance(resource, str) for resource in required_resources):
        raise _unsupported_witness_template("template required_resources must be a string array")

    descriptions = harvest_kvm_descriptions(syz_root)
    families = template_witness_families(template)
    unsupported = [family for family in families if family not in descriptions["syscalls"]]
    if unsupported:
        unsupported_text = ", ".join(sorted(dict.fromkeys(unsupported)))
        raise _unsupported_witness_template(
            f"representative template needs future runnable-witness support: {unsupported_text}"
        )

    plan_steps = ordered_plan_steps_with_threads(plan)
    event_threads = thread_ids_by_event(plan)
    execution_hints = plan.get("execution_hints", {})
    min_threads = int(execution_hints.get("min_threads", 1))
    concurrent = min_threads > 1 or candidate.get("flow") == "Con"

    lines: list[str] = []
    lines.append("# uaf_bridge_witness=runnable")
    lines.append(f"# candidate_id={candidate['candidate_id']}")
    lines.append(f"# candidate_schema_version={candidate['schema_version']}")
    lines.append(f"# witness_plan_schema_version={plan['schema_version']}")
    lines.append(f"# representative_entry_func={entry_func}")
    lines.append(f"# representative_entry_kind={entry_kind}")
    lines.append(f"# representative_template_id={template_id}")
    lines.append(f"# syzkaller_root={descriptions['syzkaller_root']}")
    lines.append(f"# required_resources={','.join(required_resources) if required_resources else '(none)'}")
    lines.append("# schedule_note=structural_plan_steps_are_preserved_in_comments")
    lines.append("# concrete_order_note=template_order_preserves_kvm_resource_dependencies")
    lines.append(
        f"# exec_mode threaded={1 if concurrent else 0} collide={1 if concurrent else 0} procs={max(min_threads, 1)}"
    )
    lines.append("")

    for step in plan_steps:
        lines.append(
            "# plan_step "
            f"step_index={step['step_index']} "
            f"event={step['event']} "
            f"thread={step['thread_id']} "
            f"timestamp={step['timestamp']}"
        )

    lines.append("")
    resource_vars: dict[str, str] = {}
    next_result_index = 0
    for call_index, family in enumerate(families):
        syscall = descriptions["syscalls"][family]
        event = str(syscall["event"])
        if event not in event_threads:
            raise ValueError(f"witness plan is missing a thread assignment for event {event}")
        lines.append(
            f"# call_index={call_index} family={family} event={event} thread={event_threads[event]}"
        )
        line, next_result_index = _render_family_call(family, descriptions, resource_vars, next_result_index)
        lines.append(line)

    return "\n".join(lines) + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Emit runnable narrow-KVM syz witness from candidate and witness plan")
    parser.add_argument("--candidate", required=True, help="Path to candidate.json")
    parser.add_argument("--plan", required=True, help="Path to witness_plan.json")
    parser.add_argument("--output", required=True, help="Path to witness.syz output")
    parser.add_argument("--syz-root", help="Path to syzkaller root containing sys/linux/dev_kvm.txt")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    candidate_id: str | None = None
    try:
        candidate = load_json(Path(args.candidate))
        plan = load_json(Path(args.plan))
        candidate_id = candidate.get("candidate_id") if isinstance(candidate.get("candidate_id"), str) else None
        witness_text = render_witness(candidate, plan, syz_root=args.syz_root)
        write_text(Path(args.output), witness_text)
    except Exception as exc:
        return print_cli_error("emit_witness_syz", exc, candidate_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
