#!/usr/bin/env python3
"""Emit triage_report_v1.json from a crash + candidate match.

Usage:
    python report.py \
        --crash-log path/to/crash.log \
        --target-profile path/to/target_profile.json \
        --state-model path/to/state_model_v1.json \
        --out path/to/triage_report.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from triage.parse_kasan import parse_kasan_report
from triage.match_candidate import match_crash


def build_triage_report(
    crash_text: str,
    target_profile: dict,
    state_model: dict,
    program_calls: list[str] | None = None,
) -> dict:
    """Build a triage_report_v1.json from crash text and runtime artifacts."""
    parsed = parse_kasan_report(crash_text)

    if parsed is None:
        # No KASAN report found — produce a minimal insufficient_data report.
        return _insufficient_report(
            state_model["candidate_id"],
            crash_text,
            "No KASAN report found in crash output",
        )

    candidate_match = match_crash(parsed, target_profile)

    # State summary based on program if available.
    state_summary = _assess_state(program_calls, state_model) if program_calls else {
        "prefix_valid": False,
        "resource_chain_intact": False,
        "phase_reached": "unknown",
        "order_preserved": False,
    }

    # Derive verdict.
    verdict = _derive_verdict(candidate_match, state_summary, parsed)

    crash_id = hashlib.sha256(crash_text.encode()).hexdigest()[:16]

    return {
        "candidate_id": state_model["candidate_id"],
        "schema_version": "triage_report/v1",
        "crash_id": f"crash_{crash_id}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "crash_summary": {
            "type": parsed.get("type", "unknown"),
            "allocator": parsed.get("allocator"),
            "stack_frames": parsed.get("stack_frames", []),
        },
        "candidate_match": candidate_match,
        "state_summary": state_summary,
        "verdict": verdict,
        "evidence": {
            "raw_crash_excerpt": crash_text[:2000],
            "matched_frames": list(
                set(parsed.get("stack_frames", []))
                & set(target_profile.get("focus_frames", []))
            ),
            "matched_files": list(
                set(parsed.get("source_files", []))
                & set(target_profile.get("focus_files", []))
            ),
        },
    }


def _assess_state(calls: list[str], sm: dict) -> dict:
    """Assess program state relative to the state model."""
    from orchestrator.score import _score_prefix, _score_phase_progress, _score_resource_chain

    prefix_ok = _score_prefix(calls, sm) == 1.0
    chain_ok = _score_resource_chain(calls, sm) >= 0.9
    progress = _score_phase_progress(calls, sm)

    phase = "unknown"
    if progress >= 1.0:
        phase = "trigger"
    elif progress >= 0.66:
        phase = "configure"
    elif progress >= 0.33:
        phase = "bootstrap"

    return {
        "prefix_valid": prefix_ok,
        "resource_chain_intact": chain_ok,
        "phase_reached": phase,
        "order_preserved": prefix_ok,  # In v1, order is implicit from prefix.
    }


def _derive_verdict(match: dict, state: dict, parsed: dict) -> str:
    """Derive a triage verdict from match quality and state."""
    score = match.get("match_score", 0.0)
    is_uaf = match.get("uaf_type_match", False)

    if score >= 0.7 and is_uaf and state.get("prefix_valid"):
        return "confirmed"
    if score >= 0.4 and is_uaf:
        return "plausible"
    if score >= 0.2:
        return "plausible"
    if score > 0.0:
        return "insufficient_data"
    return "unrelated"


def _insufficient_report(candidate_id: str, crash_text: str, reason: str) -> dict:
    crash_id = hashlib.sha256(crash_text.encode()).hexdigest()[:16]
    return {
        "candidate_id": candidate_id,
        "schema_version": "triage_report/v1",
        "crash_id": f"crash_{crash_id}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "crash_summary": {
            "type": "unknown",
            "allocator": None,
            "stack_frames": [],
        },
        "candidate_match": {
            "focus_frame_hit": False,
            "focus_file_hit": False,
            "free_use_hint_match": False,
            "uaf_type_match": False,
            "match_score": 0.0,
        },
        "state_summary": {
            "prefix_valid": False,
            "resource_chain_intact": False,
            "phase_reached": "unknown",
            "order_preserved": False,
        },
        "verdict": "insufficient_data",
        "evidence": {
            "raw_crash_excerpt": crash_text[:2000],
            "matched_frames": [],
            "matched_files": [],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build triage report from crash log")
    parser.add_argument("--crash-log", required=True, help="Path to crash log")
    parser.add_argument("--target-profile", required=True, help="Path to target_profile.json")
    parser.add_argument("--state-model", required=True, help="Path to state_model_v1.json")
    parser.add_argument("--out", required=True, help="Output triage report path")
    args = parser.parse_args()

    with open(args.crash_log) as f:
        crash_text = f.read()
    with open(args.target_profile) as f:
        tp = json.load(f)
    with open(args.state_model) as f:
        sm = json.load(f)

    report = build_triage_report(crash_text, tp, sm)

    with open(args.out, "w") as f:
        json.dump(report, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"Triage verdict: {report['verdict']} (score={report['candidate_match']['match_score']:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
