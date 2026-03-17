"""Load and validate bridge-generated mock_seed.json files for MOCK-side consumption."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common.cli import print_cli_error
from common.io import load_json, write_json
from common.schema_validation import validate_mock_seed


def import_seed(seed_payload: dict[str, Any]) -> dict[str, Any]:
    validate_mock_seed(seed_payload)
    setup_sequence = seed_payload.get("setup_sequence", [])
    trigger_sequence = seed_payload.get("trigger_sequence", [])
    mutation_hints = seed_payload.get("mutation_hints", {})

    imported = {
        "adapter_version": "mock_adapter/v1",
        "candidate_id": seed_payload["candidate_id"],
        "corpus_program": {
            "setup_calls": [step["text"] for step in setup_sequence if isinstance(step, dict)],
            "trigger_calls": [step["text"] for step in trigger_sequence if isinstance(step, dict)],
            "threads": seed_payload["threads"],
        },
        "metadata": {
            "arch": seed_payload["arch"],
            "flow": seed_payload["flow"],
            "subsystem": seed_payload["subsystem"],
            "target": seed_payload["target"],
        },
        "mutation_policy": {
            "focus_syscall_families": mutation_hints.get("focus_syscall_families", []),
            "keep_ordering_edges": mutation_hints.get("keep_ordering_edges", []),
            "mutate_near_steps": mutation_hints.get("mutate_near_steps", []),
            "prefer_collide": mutation_hints.get("prefer_collide", False),
            "prefer_two_thread_schedule": mutation_hints.get("prefer_two_thread_schedule", False),
            "preserve_prefix_len": mutation_hints.get("preserve_prefix_len", 0),
            "stable_prefix_resources": mutation_hints.get("stable_prefix_resources", []),
        },
        "ordering": seed_payload.get("ordering", []),
        "predicates": seed_payload.get("predicates", []),
        "resource_dependencies": seed_payload.get("resource_dependencies", []),
    }
    return imported


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import bridge mock_seed.json into MOCK-adapter JSON")
    parser.add_argument("--input", required=True, help="Path to mock_seed.json")
    parser.add_argument("--output", required=True, help="Path to adapter JSON output")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    candidate_id: str | None = None
    try:
        seed = load_json(Path(args.input))
        candidate_id = seed.get("candidate_id") if isinstance(seed.get("candidate_id"), str) else None
        imported = import_seed(seed)
        write_json(Path(args.output), imported)
    except Exception as exc:
        return print_cli_error("import_seed", exc, candidate_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
