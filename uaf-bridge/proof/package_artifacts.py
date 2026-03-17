from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common.cli import print_cli_error
from common.io import load_json, write_json, write_text
from common.schema_validation import validate_candidate, validate_witness_plan


def build_summary(candidate: dict[str, Any], plan: dict[str, Any], witness_path: str) -> dict[str, Any]:
    validate_candidate(candidate)
    validate_witness_plan(plan)
    if candidate.get("candidate_id") != plan.get("candidate_id"):
        raise ValueError("candidate_id mismatch between candidate and witness plan")

    entries = candidate.get("entries", [])
    entry_summaries = []
    for entry in entries:
        if isinstance(entry, dict):
            entry_summaries.append(
                {
                    "entry_func": entry.get("entry_func"),
                    "entry_kind": entry.get("entry_kind"),
                    "support_level": entry.get("support_level"),
                    "supported": entry.get("supported"),
                    "unsupported_reasons": entry.get("unsupported_reasons"),
                }
            )

    return {
        "candidate_id": candidate["candidate_id"],
        "candidate_schema_version": candidate.get("schema_version"),
        "entry_classifications": entry_summaries,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "limitations": [
            "Witness plan is structural only; exact syscall argument synthesis is not implemented.",
            "witness.syz is a pseudo-syz scaffold for inspection and downstream realization, not a guaranteed runnable syzkaller program.",
        ],
        "source": candidate.get("source"),
        "status": plan.get("status"),
        "sat": plan.get("sat"),
        "step_count": len(plan.get("ordered_steps", [])) if isinstance(plan.get("ordered_steps"), list) else 0,
        "steps": plan.get("ordered_steps"),
        "threads": plan.get("threads"),
        "witness_file": witness_path,
        "witness_plan_schema_version": plan.get("schema_version"),
    }


def render_proof_markdown(candidate: dict[str, Any], plan: dict[str, Any], witness_path: str) -> str:
    summary = build_summary(candidate, plan, witness_path)
    lines = [
        f"# Proof Bundle for {summary['candidate_id']}",
        "",
        "## Summary",
        f"- Candidate ID: `{summary['candidate_id']}`",
        f"- Candidate schema: `{summary['candidate_schema_version']}`",
        f"- Witness plan schema: `{summary['witness_plan_schema_version']}`",
        f"- Solver status: `{summary['status']}`",
        f"- SAT: `{summary['sat']}`",
        f"- Witness file: `{summary['witness_file']}`",
        f"- Generated at (UTC): `{summary['generated_at_utc']}`",
        "",
        "## Source",
        f"- Tool: `{candidate['source']['tool']}`",
        f"- Version: `{candidate['source']['version']}`",
        f"- Raw file: `{candidate['source']['raw_file']}`",
        "",
        "## Entry Classifications",
    ]
    for entry in summary["entry_classifications"]:
        lines.append(
            "- "
            f"`{entry['entry_func']}` -> `{entry['entry_kind']}` "
            f"(supported={entry['supported']}, support_level={entry['support_level']}, "
            f"unsupported_reasons={entry['unsupported_reasons']})"
        )

    lines.extend(["", "## Ordered Steps"])
    for step in summary["steps"]:
        lines.append(
            f"- step_index={step['step_index']} timestamp={step['timestamp']} event=`{step['event']}`"
        )

    lines.extend(["", "## Limitations"])
    for limitation in summary["limitations"]:
        lines.append(f"- {limitation}")

    return "\n".join(lines) + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Package proof/debug artifacts for a witness slice")
    parser.add_argument("--candidate", required=True, help="Path to candidate.json")
    parser.add_argument("--plan", required=True, help="Path to witness_plan.json")
    parser.add_argument("--witness", required=True, help="Path to witness.syz")
    parser.add_argument("--output-dir", required=True, help="Directory to write proof artifacts into")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    candidate_id: str | None = None
    try:
        candidate = load_json(Path(args.candidate))
        plan = load_json(Path(args.plan))
        witness_path = Path(args.witness)
        if not witness_path.exists():
            raise ValueError(f"witness file not found: {witness_path}")
        candidate_id = candidate.get("candidate_id") if isinstance(candidate.get("candidate_id"), str) else None
        summary = build_summary(candidate, plan, str(witness_path))
        proof_md = render_proof_markdown(candidate, plan, str(witness_path))
        output_dir = Path(args.output_dir)
        write_json(output_dir / "summary.json", summary)
        write_text(output_dir / "proof.md", proof_md)
    except Exception as exc:
        return print_cli_error("package_artifacts", exc, candidate_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
