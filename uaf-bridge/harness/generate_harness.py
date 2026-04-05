"""Generate a narrow arm64 KVM micro-harness from candidate and witness plan."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common.cli import print_cli_error
from common.io import load_json, write_text
from common.schema_validation import validate_candidate, validate_witness_plan
from harness.generic_templates import render_generic_harness
from harness.kvm_templates import build_kvm_timer_context, render_kvm_timer_harness


def render_harness(candidate: dict[str, Any], plan: dict[str, Any]) -> str:
    validate_candidate(candidate)
    validate_witness_plan(plan)

    if candidate.get("candidate_id") != plan.get("candidate_id"):
        raise ValueError("candidate_id mismatch between candidate and witness plan")
    if not plan.get("sat", False):
        raise ValueError("witness plan is UNSAT; cannot generate a micro-harness")

    analysis_context = candidate.get("analysis_context")
    subsystem = analysis_context.get("subsystem") if isinstance(analysis_context, dict) else None
    if subsystem != "kvm":
        return render_generic_harness(candidate, plan)

    context = build_kvm_timer_context(candidate, plan)
    return render_kvm_timer_harness(context)


def generate_harness(candidate_path: str | Path, plan_path: str | Path, output_path: str | Path) -> str:
    candidate = load_json(Path(candidate_path))
    plan = load_json(Path(plan_path))
    harness_text = render_harness(candidate, plan)
    write_text(Path(output_path), harness_text)
    return harness_text


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a narrow arm64 KVM micro-harness")
    parser.add_argument("--candidate", required=True, help="Path to candidate.json")
    parser.add_argument("--plan", required=True, help="Path to witness_plan.json")
    parser.add_argument("--output", required=True, help="Path to output harness.c")
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    candidate_id: str | None = None
    try:
        candidate = load_json(Path(args.candidate))
        plan = load_json(Path(args.plan))
        candidate_id = str(candidate.get("candidate_id", "")) or None
        harness_text = render_harness(candidate, plan)
        write_text(Path(args.output), harness_text)
        print(f"Generated harness for {candidate.get('candidate_id', '')}: {args.output}")
        return 0
    except Exception as error:  # pragma: no cover - exercised through CLI tests
        return print_cli_error("generate_harness", error, candidate_id=candidate_id)


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
