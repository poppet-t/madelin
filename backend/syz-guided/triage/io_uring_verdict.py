from __future__ import annotations

from typing import Any


VERDICT_CLASSES = {
    "candidate-correlated crash",
    "probable unrelated crash",
    "hang/stall/timeout",
    "no crash but target path exercised",
    "no meaningful target-path exercise",
    "unsupported/insufficient evidence",
}


def classify_io_uring_runtime_verdict(
    execution_trace_summary: dict[str, Any],
    candidate_alignment_report: dict[str, Any],
    preserved_prefix_report: dict[str, Any],
    concurrency_window_report: dict[str, Any],
) -> dict[str, Any]:
    """Classify aggregate io_uring runtime outcome into an operator-facing verdict."""
    timeouts = int(execution_trace_summary.get("timeouts", 0) or 0)
    crashes = int(execution_trace_summary.get("crashes_detected", 0) or 0)
    executed = int(execution_trace_summary.get("seeds_executed", 0) or 0)
    trigger_reached = int(execution_trace_summary.get("trigger_phase_reached", 0) or 0)

    best_match = float(candidate_alignment_report.get("best_match_score", 0.0) or 0.0)
    uaf_match = bool(candidate_alignment_report.get("any_uaf_type_match", False))
    prefix_ok_rate = float(preserved_prefix_report.get("prefix_valid_rate", 0.0) or 0.0)
    concurrency_attempted = bool(concurrency_window_report.get("overlap_window_attempted", False))

    reasons: list[str] = []

    if crashes > 0 and uaf_match and best_match >= 0.65 and prefix_ok_rate >= 0.9:
        reasons.append("At least one crash aligned with io_uring candidate signals and preserved prefix.")
        if trigger_reached > 0:
            reasons.append("Trigger phase was reached before the correlated crash.")
        verdict = "candidate-correlated crash"
    elif crashes > 0:
        reasons.append("Crash observed but candidate correlation is weak.")
        verdict = "probable unrelated crash"
    elif timeouts > 0:
        reasons.append("At least one seed timed out or stalled during execution.")
        verdict = "hang/stall/timeout"
    elif executed == 0:
        reasons.append("No seeds were executed successfully.")
        verdict = "unsupported/insufficient evidence"
    elif trigger_reached > 0 and prefix_ok_rate >= 0.9 and concurrency_attempted:
        reasons.append("io_uring lifecycle trigger paths were exercised with preserved prefix.")
        verdict = "no crash but target path exercised"
    elif trigger_reached > 0:
        reasons.append("Some trigger-path execution observed, but quality signals are weak.")
        verdict = "no meaningful target-path exercise"
    else:
        reasons.append("Execution did not reach meaningful io_uring trigger paths.")
        verdict = "no meaningful target-path exercise"

    return {
        "verdict_class": verdict,
        "reasons": reasons,
        "signals": {
            "seeds_executed": executed,
            "crashes_detected": crashes,
            "timeouts": timeouts,
            "trigger_phase_reached": trigger_reached,
            "best_match_score": best_match,
            "any_uaf_type_match": uaf_match,
            "prefix_valid_rate": prefix_ok_rate,
            "overlap_window_attempted": concurrency_attempted,
        },
    }
