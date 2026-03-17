"""Emit a deterministic pseudo-syzkaller witness scaffold from candidate and witness plan."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common.cli import print_cli_error
from common.io import load_json, write_text
from common.schema_validation import validate_candidate, validate_witness_plan


def select_representative_template(candidate: dict[str, Any], plan: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
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
        raise ValueError("No syscall template available in candidate entries")

    ordered = sorted(candidates, key=lambda item: (item[0], item[1], str(item[2].get("template_id", ""))))
    for entry_func, entry_kind, template in ordered:
        if template.get("template_id") == selected_template_id:
            return entry_func, entry_kind, template
    return ordered[0]


def render_witness(candidate: dict[str, Any], plan: dict[str, Any]) -> str:
    """Render pseudo-syz witness text from candidate and witness plan."""
    validate_candidate(candidate)
    validate_witness_plan(plan)

    if not plan.get("sat", False):
        raise ValueError("witness plan is UNSAT; cannot emit witness scaffold")
    if candidate.get("candidate_id") != plan.get("candidate_id"):
        raise ValueError("candidate_id mismatch between candidate and witness plan")

    entry_func, entry_kind, template = select_representative_template(candidate, plan)
    template_id = template.get("template_id", "unknown_template")
    calls = template.get("calls", [])
    resources = template.get("required_resources", [])
    if not isinstance(calls, list) or not all(isinstance(call, str) for call in calls):
        raise ValueError("template calls must be a string array")
    if not isinstance(resources, list) or not all(isinstance(resource, str) for resource in resources):
        raise ValueError("template required_resources must be a string array")

    ordered_steps = plan.get("ordered_steps")
    threads = plan.get("threads")
    if not isinstance(ordered_steps, list) or not ordered_steps:
        raise ValueError("witness plan has no ordered steps")
    if not isinstance(threads, list) or not threads:
        raise ValueError("witness plan has no thread schedule")

    lines: list[str] = []
    lines.append("# UAF Witness Bridge pseudo-syz scaffold")
    lines.append("# NOTE: This is a deterministic, proof/debug scaffold, not a fully runnable syzkaller program.")
    lines.append("# NOTE: Exact argument synthesis and environment realization remain intentionally out of scope for v1.")
    lines.append(f"# candidate_id: {candidate['candidate_id']}")
    lines.append(f"# candidate_schema_version: {candidate['schema_version']}")
    lines.append(f"# witness_plan_schema_version: {plan['schema_version']}")
    lines.append(f"# representative_entry_func: {entry_func}")
    lines.append(f"# representative_entry_kind: {entry_kind}")
    lines.append(f"# representative_template_id: {template_id}")
    lines.append("")
    lines.append("# setup:")
    lines.append(f"#   required_resources: {', '.join(resources) if resources else '(none)'}")
    lines.append("")
    lines.append("# ordered_steps:")
    for step in ordered_steps:
        if isinstance(step, dict):
            lines.append(
                f"#   - step_index={step['step_index']} t={step['timestamp']} event={step['event']}"
            )

    barriers = plan.get("barriers", [])
    lines.append("")
    lines.append("# barriers:")
    if isinstance(barriers, list) and barriers:
        for edge in barriers:
            if isinstance(edge, dict):
                lines.append(f"#   - {edge['before']} < {edge['after']} ({edge['reason']})")
    else:
        lines.append("#   - (none)")

    predicates = plan.get("predicates", [])
    lines.append("")
    lines.append("# predicates:")
    if isinstance(predicates, list) and predicates:
        for predicate in predicates:
            if isinstance(predicate, dict):
                lines.append(
                    f"#   - {predicate['name']} at {predicate['must_hold_at']} scope={predicate['scope']}"
                )
    else:
        lines.append("#   - (none)")

    execution_hints = plan.get("execution_hints", {})
    lines.append("")
    lines.append("# execution_hints:")
    lines.append(f"#   candidate_flow: {execution_hints.get('candidate_flow')}")
    lines.append(f"#   min_threads: {execution_hints.get('min_threads')}")

    for thread in threads:
        if not isinstance(thread, dict):
            continue
        thread_id = thread.get("thread_id")
        steps = thread.get("steps", [])
        if not isinstance(thread_id, int) or not isinstance(steps, list):
            continue

        lines.append("")
        lines.append(f"thread_{thread_id} {{")
        for step in steps:
            if not isinstance(step, dict):
                continue
            event = step.get("event")
            timestamp = step.get("timestamp")
            step_index = step.get("step_index")
            if not isinstance(event, str) or not isinstance(timestamp, int) or not isinstance(step_index, int):
                continue
            lines.append(f"  # step_index={step_index} t={timestamp} event={event}")
            for call in calls:
                lines.append(f"  {call}")
        lines.append("}")

    return "\n".join(lines) + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Emit pseudo-syz witness from candidate and witness plan")
    parser.add_argument("--candidate", required=True, help="Path to candidate.json")
    parser.add_argument("--plan", required=True, help="Path to witness_plan.json")
    parser.add_argument("--output", required=True, help="Path to witness.syz output")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    candidate_id: str | None = None
    try:
        candidate = load_json(Path(args.candidate))
        plan = load_json(Path(args.plan))
        candidate_id = candidate.get("candidate_id") if isinstance(candidate.get("candidate_id"), str) else None
        witness_text = render_witness(candidate, plan)
        write_text(Path(args.output), witness_text)
    except Exception as exc:
        return print_cli_error("emit_witness_syz", exc, candidate_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
