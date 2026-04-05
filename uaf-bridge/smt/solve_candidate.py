"""Solve normalized candidates and emit witness plan JSON."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from z3 import sat

from common.cli import print_cli_error
from common.io import load_json, write_json
from common.schema_validation import validate_candidate, validate_witness_plan
from smt.encode_candidate import encode_candidate
from smt.extract_schedule import build_barriers, canonical_ordered_steps, canonical_thread_map, group_steps_by_thread

SCHEMA_VERSION = "witness_plan/v1"


def _first_template_hint(candidate: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    entries = candidate.get("entries", [])
    if not isinstance(entries, list):
        return None, None, None

    ordered_entries = sorted(
        [entry for entry in entries if isinstance(entry, dict)],
        key=lambda entry: (
            str(entry.get("support_level", "")),
            str(entry.get("entry_func", "")),
            str(entry.get("entry_kind", "")),
        ),
    )

    for entry in ordered_entries:
        templates = entry.get("syscall_templates")
        if not isinstance(templates, list) or not templates:
            continue
        first = sorted(
            [template for template in templates if isinstance(template, dict)],
            key=lambda template: str(template.get("template_id", "")),
        )[0]
        entry_func = entry.get("entry_func") if isinstance(entry.get("entry_func"), str) else None
        entry_kind = entry.get("entry_kind") if isinstance(entry.get("entry_kind"), str) else None
        template_id = first.get("template_id") if isinstance(first.get("template_id"), str) else None
        return entry_func, entry_kind, template_id

    return None, None, None


def _predicate_records(candidate: dict[str, Any]) -> list[dict[str, str]]:
    predicates = candidate.get("constraints", {}).get("predicates", [])
    normalized: list[dict[str, str]] = []
    if not isinstance(predicates, list):
        return normalized

    for predicate in predicates:
        if not isinstance(predicate, dict):
            continue
        name = predicate.get("name")
        must_hold_at = predicate.get("must_hold_at")
        scope = predicate.get("scope")
        if isinstance(name, str) and isinstance(must_hold_at, str) and isinstance(scope, str):
            normalized.append({"must_hold_at": must_hold_at, "name": name, "scope": scope})
    return sorted(normalized, key=lambda item: (item["name"], item["must_hold_at"], item["scope"]))


def _model_dict(encoded: Any, model: Any) -> dict[str, Any]:
    timestamps = {
        event: model.eval(var, model_completion=True).as_long() for event, var in encoded.time_vars.items()
    }
    threads = {event: model.eval(var, model_completion=True).as_long() for event, var in encoded.thread_vars.items()}
    return {"threads": dict(sorted(threads.items())), "timestamps": dict(sorted(timestamps.items()))}


def solve_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Solve one candidate and return a witness_plan payload."""
    validate_candidate(candidate)
    encoded = encode_candidate(candidate)
    result = encoded.optimizer.check()

    entry_func, entry_kind, template_id = _first_template_hint(candidate)
    predicates = _predicate_records(candidate)
    barriers = build_barriers(encoded.partial_order)

    execution_hints = {
        "candidate_flow": encoded.flow,
        "entry_selection": {
            "entry_func": entry_func,
            "entry_kind": entry_kind,
            "template_id": template_id,
        },
        "min_threads": encoded.min_threads,
        "notes": [
            "Structural witness only: ordering, thread assignment, and readiness predicates are encoded.",
            "Exact syscall argument synthesis remains intentionally out of scope for v1.",
        ],
    }

    debug = {
        "check_result": str(result),
        "encoded_event_count": len(encoded.events),
        "encoded_events": list(encoded.events),
        "input_mapping_confidence": candidate.get("status", {}).get("mapping_confidence"),
        "soft_constraints": encoded.soft_constraints,
        "solver": "z3.Optimize",
        "unsat_reasons": [],
    }

    if result == sat:
        model = encoded.optimizer.model()
        model_payload = _model_dict(encoded, model)
        ordered_steps = canonical_ordered_steps(encoded.events, encoded.partial_order)
        threads = group_steps_by_thread(ordered_steps, canonical_thread_map(encoded.events, encoded.flow, encoded.min_threads))
        plan = {
            "barriers": barriers,
            "candidate_id": candidate["candidate_id"],
            "debug": debug,
            "execution_hints": execution_hints,
            "ordered_steps": ordered_steps,
            "predicates": predicates,
            "sat": True,
            "schema_version": SCHEMA_VERSION,
            "status": "sat",
            "threads": threads,
        }
        validate_witness_plan(plan)
        return plan

    debug["unsat_reasons"] = ["No satisfying model under current structural constraints."]
    plan = {
        "barriers": barriers,
        "candidate_id": candidate["candidate_id"],
        "debug": debug,
        "execution_hints": execution_hints,
        "ordered_steps": [],
        "predicates": predicates,
        "sat": False,
        "schema_version": SCHEMA_VERSION,
        "status": "unsat",
        "threads": [],
    }
    validate_witness_plan(plan)
    return plan


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Solve candidate JSON with Z3")
    parser.add_argument("--input", required=True, help="Path to normalized candidate JSON")
    parser.add_argument("--output", required=True, help="Path to output witness plan JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    candidate_id: str | None = None
    try:
        candidate = load_json(Path(args.input))
        candidate_id = candidate.get("candidate_id") if isinstance(candidate.get("candidate_id"), str) else None
        validate_candidate(candidate)
        plan = solve_candidate(candidate)
        validate_witness_plan(plan)
        write_json(Path(args.output), plan)
    except Exception as exc:
        return print_cli_error("solve_candidate", exc, candidate_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
