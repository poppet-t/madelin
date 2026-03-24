from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .match_candidate import load_candidate_record, match_candidate
from .parse_crash import parse_crash_file


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    return payload


def load_run_results(output_dir: str | Path) -> list[dict[str, Any]]:
    base = Path(output_dir)
    results = [
        _load_json(path)
        for path in sorted(base.glob("runs/*/run-*/result.json"))
        if path.is_file()
    ]
    return results


def _match_priority(match_result: dict[str, Any]) -> tuple[int, int]:
    verdict_weight = {
        "CONFIRMED": 5,
        "UNRELATED_CRASH": 4,
        "SETUP_FAILED": 3,
        "TIMING_INCONCLUSIVE": 2,
        "REACHED_NO_CRASH": 1,
        "PATH_INFEASIBLE": 0,
    }
    confidence_weight = {"high": 2, "medium": 1, "low": 0}
    return (
        verdict_weight.get(str(match_result.get("verdict")), -1),
        confidence_weight.get(str(match_result.get("confidence")), -1),
    )


def _group_key(timing_us: int) -> str:
    return f"{timing_us}us"


def _best_timing_payload(runs_by_timing: dict[str, dict[str, Any]]) -> tuple[int | None, float]:
    ranking: list[tuple[int, int, int, int, int]] = []
    for label, payload in runs_by_timing.items():
        timing_us = int(payload["timing_us"])
        ranking.append(
            (
                int(payload["crashes_matched"]),
                int(payload["timing_window_runs"]),
                int(payload["candidate_reached_runs"]),
                -int(payload["setup_failures"]),
                -timing_us,
            )
        )

    if not ranking:
        return None, 0.0

    best_label, best_payload = max(
        runs_by_timing.items(),
        key=lambda item: (
            int(item[1]["crashes_matched"]),
            int(item[1]["timing_window_runs"]),
            int(item[1]["candidate_reached_runs"]),
            -int(item[1]["setup_failures"]),
            -int(item[1]["timing_us"]),
        ),
    )
    runs = int(best_payload["runs"]) or 1
    crash_rate = float(best_payload["crashes_matched"]) / float(runs)
    return int(best_payload["timing_us"]), crash_rate


def _timing_sensitivity(runs_by_timing: dict[str, dict[str, Any]]) -> str:
    matched_timings = [payload for payload in runs_by_timing.values() if int(payload["crashes_matched"]) > 0]
    if len(matched_timings) == 1:
        return "high"
    if len(matched_timings) > 1:
        return "medium"

    timing_window_values = {int(payload["timing_window_runs"]) for payload in runs_by_timing.values()}
    if len(timing_window_values) > 1:
        return "medium"
    return "low"


def aggregate_verdict(
    *,
    output_dir: str | Path,
    candidate_path: str | Path,
    execution_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    candidate_payload = load_candidate_record(candidate_path)
    execution_metadata = dict(execution_metadata or {})
    execution_metadata["candidate_source"] = str(candidate_path)

    run_results = load_run_results(output_dir)
    if not run_results:
        raise FileNotFoundError(f"no harness run results found under {output_dir / 'runs'}")

    runs_by_timing: dict[str, dict[str, Any]] = {}
    verdict_counts = {
        "CONFIRMED": 0,
        "UNRELATED_CRASH": 0,
        "SETUP_FAILED": 0,
        "TIMING_INCONCLUSIVE": 0,
        "REACHED_NO_CRASH": 0,
        "PATH_INFEASIBLE": 0,
    }
    best_match: dict[str, Any] | None = None

    runs_total = 0
    crashes_total = 0
    crashes_matched = 0
    setup_failures = 0
    candidate_reached_runs = 0
    timing_window_runs = 0
    completed_runs = 0

    for result in run_results:
        timing_us = int(result.get("timing_us", 0))
        label = _group_key(timing_us)
        bucket = runs_by_timing.setdefault(
            label,
            {
                "timing_us": timing_us,
                "runs": 0,
                "crashes_total": 0,
                "crashes_matched": 0,
                "setup_failures": 0,
                "candidate_reached_runs": 0,
                "timing_window_runs": 0,
                "completed_runs": 0,
            },
        )

        run_metadata = {
            "setup_failed": bool(result.get("setup_failed", False)),
            "candidate_reached": bool(result.get("candidate_reached", False)),
            "timing_window_entered": bool(result.get("timing_window_entered", False)),
            "execution_completed": bool(result.get("execution_completed", False)),
        }
        crash_log_path = Path(str(result["crash_log"])) if result.get("crash_log") else None
        parsed_crash = parse_crash_file(crash_log_path) if crash_log_path and crash_log_path.is_file() else None
        match_result = match_candidate(parsed_crash, candidate_payload, run_metadata)

        if parsed_crash is not None:
            evidence = dict(match_result["evidence"])
            evidence["crash_log"] = str(crash_log_path)
            match_result = dict(match_result)
            match_result["evidence"] = evidence

        runs_total += 1
        bucket["runs"] += 1
        if parsed_crash is not None:
            crashes_total += 1
            bucket["crashes_total"] += 1
        if match_result["verdict"] == "CONFIRMED":
            crashes_matched += 1
            bucket["crashes_matched"] += 1
        if run_metadata["setup_failed"]:
            setup_failures += 1
            bucket["setup_failures"] += 1
        if run_metadata["candidate_reached"]:
            candidate_reached_runs += 1
            bucket["candidate_reached_runs"] += 1
        if run_metadata["timing_window_entered"]:
            timing_window_runs += 1
            bucket["timing_window_runs"] += 1
        if run_metadata["execution_completed"]:
            completed_runs += 1
            bucket["completed_runs"] += 1

        verdict_counts[str(match_result["verdict"])] += 1
        if best_match is None or _match_priority(match_result) > _match_priority(best_match):
            best_match = match_result

    if crashes_matched > 0:
        verdict = "CONFIRMED"
        confidence = "high"
    elif verdict_counts["UNRELATED_CRASH"] > 0:
        verdict = "UNRELATED_CRASH"
        confidence = best_match["confidence"] if best_match is not None else "low"
    elif setup_failures == runs_total:
        verdict = "SETUP_FAILED"
        confidence = "medium"
    elif timing_window_runs > 0:
        verdict = "TIMING_INCONCLUSIVE"
        confidence = "medium"
    elif candidate_reached_runs > 0 or completed_runs > 0:
        verdict = "REACHED_NO_CRASH"
        confidence = "low"
    else:
        verdict = "PATH_INFEASIBLE"
        confidence = "low"

    evidence = dict(best_match["evidence"]) if best_match is not None else {}
    evidence["aggregate"] = {
        "verdict_counts": verdict_counts,
        "candidate_reached_runs": candidate_reached_runs,
        "timing_window_runs": timing_window_runs,
    }

    ordered_runs_by_timing = {
        key: runs_by_timing[key]
        for key in sorted(runs_by_timing.keys(), key=lambda item: int(item[:-2]))
    }
    best_timing_us, crash_rate_at_best = _best_timing_payload(ordered_runs_by_timing)

    execution = {
        "candidate_source": execution_metadata["candidate_source"],
        "execution_mode": execution_metadata.get("execution_mode", "harness_timing_sweep"),
        "remote_host": execution_metadata.get("remote_host"),
        "harness_source": execution_metadata.get("harness_source"),
        "runs": runs_total,
        "runs_total": runs_total,
        "wall_seconds": int(execution_metadata.get("wall_seconds", 0)),
        "crashes_total": crashes_total,
        "crashes_matched": crashes_matched,
        "setup_failures": setup_failures,
        "candidate_reached_runs": candidate_reached_runs,
        "timing_window_runs": timing_window_runs,
        "completed_runs": completed_runs,
        "best_timing_us": best_timing_us,
        "crash_rate_at_best": crash_rate_at_best,
        "timing_sensitivity": _timing_sensitivity(ordered_runs_by_timing),
        "runs_by_timing": ordered_runs_by_timing,
        "run_results_scanned": [
            str(path)
            for path in sorted(output_dir.glob("runs/*/run-*/result.json"))
            if path.is_file()
        ],
    }

    verdict_record = {
        "candidate_id": candidate_payload.get("candidate_id", ""),
        "verdict": verdict,
        "confidence": confidence,
        "evidence": evidence,
        "execution": execution,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    verdict_path = output_dir / "verdict.json"
    verdict_path.parent.mkdir(parents=True, exist_ok=True)
    verdict_path.write_text(json.dumps(verdict_record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return verdict_record


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate timing-sweep harness results into verdict.json")
    parser.add_argument("--output-dir", required=True, help="Harness output directory containing runs/*/run-*/result.json")
    parser.add_argument("--candidate", required=True, help="Explicit candidate.json path")
    parser.add_argument("--wall-seconds", type=int, default=0, help="Observed wall-clock runtime in seconds")
    parser.add_argument("--execution-mode", default="harness_timing_sweep", help="Execution mode label")
    parser.add_argument("--remote-host", help="SSH target host used for the execution")
    parser.add_argument("--harness-source", help="Source harness.c path used for the execution")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    verdict = aggregate_verdict(
        output_dir=args.output_dir,
        candidate_path=args.candidate,
        execution_metadata={
            "wall_seconds": args.wall_seconds,
            "execution_mode": args.execution_mode,
            "remote_host": args.remote_host,
            "harness_source": args.harness_source,
        },
    )
    print(
        f"Aggregate verdict: {verdict['verdict']} ({verdict['confidence']}) "
        f"for {verdict['candidate_id']}"
    )
    print(f"Verdict written to: {Path(args.output_dir) / 'verdict.json'}")


if __name__ == "__main__":
    main()
