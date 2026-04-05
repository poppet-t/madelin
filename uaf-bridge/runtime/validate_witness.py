"""Validate runnable narrow-KVM witness programs locally."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
from typing import Any

from common.cli import print_cli_error
from common.io import load_json
from common.schema_validation import validate_candidate, validate_witness_plan
from mapping.syz_descriptions import (
    INTEGER_SIZES,
    _parse_field_type_size,
    harvest_kvm_descriptions,
    split_top_level_items,
)
from runtime.emit_witness_syz import (
    ordered_plan_steps_with_threads,
    render_witness,
    select_representative_template,
    template_witness_families,
    thread_ids_by_event,
)


CALL_PATTERN = re.compile(r"^(?:(r\d+)\s*=\s*)?([A-Za-z0-9_$]+)\((.*)\)$")
ADDRESS_POINTER_PATTERN = re.compile(r"^&\((0x[0-9a-fA-F]+)(?:/0x[0-9a-fA-F]+)?\)=(.+)$")


def _parse_comment_fields(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for part in text.split():
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        parsed[key] = value
    return parsed


def _parse_witness(witness_text: str) -> dict[str, Any]:
    plan_steps: list[dict[str, int | str]] = []
    calls: list[dict[str, Any]] = []
    pending_call_meta: dict[str, str] | None = None

    for line_no, raw_line in enumerate(witness_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("# "):
            body = line[2:]
            if body.startswith("plan_step "):
                fields = _parse_comment_fields(body[len("plan_step ") :])
                plan_steps.append(
                    {
                        "event": fields["event"],
                        "step_index": int(fields["step_index"], 0),
                        "thread_id": int(fields["thread"], 0),
                        "timestamp": int(fields["timestamp"], 0),
                    }
                )
            elif body.startswith("call_index="):
                if pending_call_meta is not None:
                    raise ValueError("witness has a call metadata comment without a following syscall line")
                pending_call_meta = _parse_comment_fields(body)
            continue

        match = CALL_PATTERN.fullmatch(line)
        if match is None:
            raise ValueError(f"witness has an unparseable syscall line at {line_no}: {raw_line}")
        args = split_top_level_items(match.group(3))
        calls.append(
            {
                "args": args,
                "line_no": line_no,
                "metadata": pending_call_meta or {},
                "result_var": match.group(1),
                "syz_name": match.group(2),
            }
        )
        pending_call_meta = None

    if pending_call_meta is not None:
        raise ValueError("witness ends with a call metadata comment that is not attached to a syscall line")
    if not calls:
        raise ValueError("witness contains no syscall lines")
    return {"calls": calls, "plan_steps": plan_steps}


def _parse_int_literal(text: str) -> int:
    return int(text, 0)


def _extract_pointer_payload(arg: str) -> str:
    if arg.startswith("&AUTO="):
        return arg[len("&AUTO=") :]
    match = ADDRESS_POINTER_PATTERN.fullmatch(arg)
    if match is not None:
        return match.group(2)
    raise ValueError(f"expected pointer literal, got: {arg}")


def _validate_scalar_literal(type_expr: str, literal: str) -> int:
    _parse_int_literal(literal)
    if type_expr in INTEGER_SIZES:
        return INTEGER_SIZES[type_expr]
    if type_expr.startswith("const[") or type_expr.startswith("flags[") or type_expr.startswith("len["):
        return _parse_field_type_size(type_expr, {})
    raise ValueError(f"unsupported scalar field type in witness validator: {type_expr}")


def _struct_literal_size(struct_name: str, literal: str, descriptions: dict[str, Any]) -> int:
    if not literal.startswith("{") or not literal.endswith("}"):
        raise ValueError(f"{struct_name} witness literal must use struct syntax")

    struct_desc = descriptions["structs"][struct_name]
    field_literals = split_top_level_items(literal[1:-1])
    fields = struct_desc["fields"]
    if len(field_literals) != len(fields):
        raise ValueError(f"{struct_name} witness literal has {len(field_literals)} fields, expected {len(fields)}")

    struct_sizes = {name: int(payload["size"]) for name, payload in descriptions["structs"].items()}
    total_size = 0
    for field, field_literal in zip(fields, field_literals, strict=True):
        type_expr = str(field["type"])
        field_literal = field_literal.strip()
        if type_expr in INTEGER_SIZES or type_expr.startswith("const[") or type_expr.startswith("flags[") or type_expr.startswith("len["):
            total_size += _validate_scalar_literal(type_expr, field_literal)
            continue
        if type_expr.startswith("array["):
            if not field_literal.startswith("[") or not field_literal.endswith("]"):
                raise ValueError(f"{struct_name}.{field['name']} witness literal must use array syntax")
            inner = type_expr[type_expr.find("[") + 1 : -1]
            elem_type, count_text = split_top_level_items(inner)
            expected_count = int(count_text, 0)
            items = split_top_level_items(field_literal[1:-1])
            if len(items) != expected_count:
                raise ValueError(
                    f"{struct_name}.{field['name']} witness array has {len(items)} items, expected {expected_count}"
                )
            for item in items:
                _validate_scalar_literal(elem_type, item.strip())
            total_size += _parse_field_type_size(type_expr, struct_sizes)
            continue
        if type_expr in descriptions["structs"]:
            total_size += _struct_literal_size(type_expr, field_literal, descriptions)
            continue
        raise ValueError(f"unsupported witness struct field type for {struct_name}.{field['name']}: {type_expr}")
    return total_size


def _validate_struct_arg(arg: str, struct_name: str, descriptions: dict[str, Any]) -> None:
    payload = _extract_pointer_payload(arg)
    size = _struct_literal_size(struct_name, payload, descriptions)
    expected = int(descriptions["structs"][struct_name]["size"])
    if size != expected:
        raise ValueError(f"{struct_name} witness literal is {size} bytes, expected {expected}")


def _validate_openat_kvm(call: dict[str, Any], descriptions: dict[str, Any]) -> None:
    constants = descriptions["constants"]
    args = call["args"]
    if len(args) != 4:
        raise ValueError("openat$kvm witness call must have 4 arguments")
    if _parse_int_literal(args[0]) != int(constants["AT_FDCWD"]):
        raise ValueError("openat$kvm witness uses the wrong AT_FDCWD constant")
    if _extract_pointer_payload(args[1]) != "'/dev/kvm\\x00'":
        raise ValueError("openat$kvm witness must target '/dev/kvm\\x00'")
    if _parse_int_literal(args[2]) != 0x2:
        raise ValueError("openat$kvm witness flags argument must request O_RDWR")
    if _parse_int_literal(args[3]) != 0:
        raise ValueError("openat$kvm witness mode argument must be 0")


def _validate_ioctl_call(
    family: str, call: dict[str, Any], descriptions: dict[str, Any], resource_vars: dict[str, str]
) -> None:
    syscall = descriptions["syscalls"][family]
    args = call["args"]
    if len(args) != len(syscall["arg_names"]):
        raise ValueError(f"{family} witness call uses {len(args)} args, expected {len(syscall['arg_names'])}")

    input_resource = syscall.get("bridge_input_resource")
    if isinstance(input_resource, str):
        if input_resource not in resource_vars:
            raise ValueError(f"{family} uses {input_resource} before it is produced")
        if args[0] != resource_vars[input_resource]:
            raise ValueError(f"{family} uses {args[0]} instead of the current {input_resource} witness variable")

    constant_name = syscall.get("constant_name")
    if isinstance(constant_name, str):
        if _parse_int_literal(args[1]) != int(descriptions["constants"][constant_name]):
            raise ValueError(f"{family} witness call uses the wrong ioctl constant")

    if family in {"KVM_CREATE_VM", "KVM_CREATE_VCPU", "KVM_RUN"}:
        if _parse_int_literal(args[2]) != 0:
            raise ValueError(f"{family} witness tail argument must be 0")
    elif family == "KVM_ARM_VCPU_INIT":
        _validate_struct_arg(args[2], "kvm_vcpu_init", descriptions)
    elif family in {"KVM_SET_ONE_REG", "KVM_GET_ONE_REG"}:
        _validate_struct_arg(args[2], "kvm_one_reg", descriptions)
    else:  # pragma: no cover - guarded by the supported family subset
        raise ValueError(f"validator does not support witness family {family}")


def validate_witness(
    candidate: dict[str, Any],
    plan: dict[str, Any],
    witness_text: str,
    syz_root: str | Path | None = None,
) -> dict[str, Any]:
    """Validate a runnable witness against the selected template and plan."""
    validate_candidate(candidate)
    validate_witness_plan(plan)

    if not plan.get("sat", False):
        raise ValueError("witness plan is UNSAT; cannot validate runnable witness")
    if candidate.get("candidate_id") != plan.get("candidate_id"):
        raise ValueError("candidate_id mismatch between candidate and witness plan")

    analysis_context = candidate.get("analysis_context")
    subsystem = analysis_context.get("subsystem") if isinstance(analysis_context, dict) else None
    if subsystem != "kvm":
        expected = render_witness(candidate, plan, syz_root=syz_root)
        if witness_text != expected:
            raise ValueError("generic pack witness does not match deterministic renderer")
        entry_func, entry_kind, template = select_representative_template(candidate, plan)
        call_count = len([line for line in witness_text.splitlines() if line and not line.startswith("#")])
        return {
            "candidate_id": candidate["candidate_id"],
            "call_count": call_count,
            "entry_func": entry_func,
            "entry_kind": entry_kind,
            "plan_step_count": len(ordered_plan_steps_with_threads(plan)),
            "representative_template_id": str(template.get("template_id", "unknown_template")),
            "syzkaller_root": "pack-generic",
            "valid": True,
        }

    entry_func, entry_kind, template = select_representative_template(candidate, plan)
    template_id = str(template.get("template_id", "unknown_template"))
    descriptions = harvest_kvm_descriptions(syz_root)
    expected_families = template_witness_families(template)
    unsupported = [family for family in expected_families if family not in descriptions["syscalls"]]
    if unsupported:
        unsupported_text = ", ".join(sorted(dict.fromkeys(unsupported)))
        raise ValueError(f"representative template needs future runnable-witness support: {unsupported_text}")

    parsed = _parse_witness(witness_text)
    expected_steps = ordered_plan_steps_with_threads(plan)
    if parsed["plan_steps"] != expected_steps:
        raise ValueError("witness plan_step metadata does not match witness_plan.json")

    calls = parsed["calls"]
    if len(calls) != len(expected_families):
        raise ValueError(
            f"witness emits {len(calls)} syscall lines, expected {len(expected_families)} from the representative template"
        )

    event_threads = thread_ids_by_event(plan)
    resource_vars: dict[str, str] = {}
    for call_index, (call, family) in enumerate(zip(calls, expected_families, strict=True)):
        syscall = descriptions["syscalls"][family]
        metadata = call["metadata"]
        if metadata.get("family") != family:
            raise ValueError(f"witness metadata family mismatch at call {call_index}: {metadata.get('family')}")
        if metadata.get("event") != syscall["event"]:
            raise ValueError(f"witness metadata event mismatch at call {call_index}: {metadata.get('event')}")
        if metadata.get("call_index") != str(call_index):
            raise ValueError(f"witness metadata call_index mismatch at call {call_index}")
        expected_thread = event_threads[str(syscall["event"])]
        if metadata.get("thread") != str(expected_thread):
            raise ValueError(f"witness metadata thread mismatch for {family}: {metadata.get('thread')}")
        if call["syz_name"] != syscall["syz_name"]:
            raise ValueError(f"witness syscall mismatch at call {call_index}: {call['syz_name']}")

        if family == "openat$KVM":
            _validate_openat_kvm(call, descriptions)
        else:
            _validate_ioctl_call(family, call, descriptions, resource_vars)

        output_resource = syscall.get("bridge_output_resource")
        if isinstance(output_resource, str):
            result_var = call.get("result_var")
            if not isinstance(result_var, str):
                raise ValueError(f"{family} witness call must assign its produced resource to a result variable")
            resource_vars[output_resource] = result_var

    return {
        "candidate_id": candidate["candidate_id"],
        "call_count": len(calls),
        "entry_func": entry_func,
        "entry_kind": entry_kind,
        "plan_step_count": len(expected_steps),
        "representative_template_id": template_id,
        "syzkaller_root": descriptions["syzkaller_root"],
        "valid": True,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate runnable narrow-KVM witness locally")
    parser.add_argument("--candidate", required=True, help="Path to candidate.json")
    parser.add_argument("--plan", required=True, help="Path to witness_plan.json")
    parser.add_argument("--witness", required=True, help="Path to witness.syz")
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
        witness_text = Path(args.witness).read_text(encoding="utf-8")
        summary = validate_witness(candidate, plan, witness_text, syz_root=args.syz_root)
        print(
            f"[validate_witness] ok [candidate_id={summary['candidate_id']}] "
            f"template={summary['representative_template_id']} calls={summary['call_count']}",
            flush=True,
        )
    except Exception as exc:
        return print_cli_error("validate_witness", exc, candidate_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
