"""Render a deterministic MOCK-oriented program scaffold from mock_seed.json."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common.cli import print_cli_error
from common.io import load_json, write_text
from common.schema_validation import validate_mock_seed


def render_mock_program(seed_payload: dict[str, Any]) -> str:
    validate_mock_seed(seed_payload)
    lines: list[str] = []
    lines.append("# MOCK adapter scaffold")
    lines.append("# This is a deterministic bridge-to-MOCK handoff artifact, not a full Healer runtime program.")
    lines.append(f"# candidate_id: {seed_payload['candidate_id']}")
    lines.append(f"# target: {seed_payload['target']}/{seed_payload['arch']} subsystem={seed_payload['subsystem']}")
    lines.append(f"# flow: {seed_payload['flow']} threads={seed_payload['threads']}")
    lines.append("")
    lines.append("[setup_sequence]")
    for idx, step in enumerate(seed_payload.get("setup_sequence", [])):
        if isinstance(step, dict):
            lines.append(f"{idx}: {step['text']}")
    lines.append("")
    lines.append("[trigger_sequence]")
    for idx, step in enumerate(seed_payload.get("trigger_sequence", [])):
        if isinstance(step, dict):
            lines.append(f"{idx}: {step['text']}")
    lines.append("")
    lines.append("[ordering]")
    for edge in seed_payload.get("ordering", []):
        if isinstance(edge, dict):
            lines.append(f"- {edge['before']} < {edge['after']} ({edge['reason']})")
    lines.append("")
    lines.append("[mutation_policy]")
    mutation_hints = seed_payload.get("mutation_hints", {})
    lines.append(f"preserve_prefix_len = {mutation_hints.get('preserve_prefix_len', 0)}")
    lines.append(f"prefer_two_thread_schedule = {str(mutation_hints.get('prefer_two_thread_schedule', False)).lower()}")
    lines.append(f"prefer_collide = {str(mutation_hints.get('prefer_collide', False)).lower()}")
    lines.append(
        "focus_syscall_families = " + ", ".join(mutation_hints.get("focus_syscall_families", []))
    )
    lines.append("mutate_near_steps = " + ", ".join(mutation_hints.get("mutate_near_steps", [])))
    lines.append("")
    lines.append("[thread_schedule]")
    for step in seed_payload.get("ordered_steps", []):
        if isinstance(step, dict):
            lines.append(
                f"t{step['thread_id']} step={step['step_index']} ts={step['timestamp']} event={step['event']}"
            )
    return "\n".join(lines) + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a MOCK-oriented textual scaffold from mock_seed.json")
    parser.add_argument("--input", required=True, help="Path to mock_seed.json")
    parser.add_argument("--output", required=True, help="Path to output text file")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    candidate_id: str | None = None
    try:
        seed = load_json(Path(args.input))
        candidate_id = seed.get("candidate_id") if isinstance(seed.get("candidate_id"), str) else None
        program_text = render_mock_program(seed)
        write_text(Path(args.output), program_text)
    except Exception as exc:
        return print_cli_error("seed_to_mock_program", exc, candidate_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
