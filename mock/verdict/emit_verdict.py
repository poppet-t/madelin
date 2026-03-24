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


def _candidate_id_from_seed_workdir(seed_workdir: Path | None) -> str | None:
    if seed_workdir is None:
        return None

    for candidate_path in (seed_workdir / "bias.json", seed_workdir / "imported_seed.json"):
        if candidate_path.is_file():
            payload = _load_json(candidate_path)
            candidate_id = payload.get("candidate_id")
            if isinstance(candidate_id, str) and candidate_id:
                return candidate_id
    return None


def resolve_candidate_path(
    *,
    candidate_path: str | Path | None = None,
    seed_workdir: str | Path | None = None,
    bridge_root: str | Path | None = None,
) -> Path:
    if candidate_path is not None:
        path = Path(candidate_path)
        if path.is_file():
            return path
        raise FileNotFoundError(f"candidate file not found: {path}")

    seed_dir = Path(seed_workdir) if seed_workdir is not None else None
    candidate_id = _candidate_id_from_seed_workdir(seed_dir)

    candidates: list[Path] = []
    if bridge_root is not None:
        out_dir = Path(bridge_root) / "out"
        candidates.extend(
            path for path in (out_dir / "uafx_kvm_candidate.json", out_dir / "candidate.json") if path.is_file()
        )
        if out_dir.is_dir():
            candidates.extend(
                path for path in sorted(out_dir.glob("*candidate*.json")) if path.is_file() and path not in candidates
            )

    if seed_dir is not None:
        imported_seed = seed_dir / "imported_seed.json"
        if imported_seed.is_file():
            candidates.append(imported_seed)

    if not candidates:
        raise FileNotFoundError("no candidate record found in bridge output or seed workdir")

    if candidate_id:
        for path in candidates:
            payload = _load_json(path)
            if payload.get("candidate_id") == candidate_id:
                return path

    return candidates[0]


def collect_crash_logs(output_dir: str | Path) -> list[Path]:
    crash_dir = Path(output_dir) / "crashes"
    if not crash_dir.is_dir():
        return []

    logs = [
        path
        for path in sorted(crash_dir.glob("*/log*"))
        if path.is_file()
    ]
    raw_logs = [
        path
        for path in sorted((crash_dir / "raw_logs").glob("*"))
        if path.is_file()
    ]
    return [*logs, *raw_logs]


def _verdict_priority(match_result: dict[str, Any]) -> tuple[int, int]:
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


def build_verdict_record(
    candidate_payload: dict[str, Any],
    match_result: dict[str, Any],
    execution_metadata: dict[str, Any],
) -> dict[str, Any]:
    execution = {
        "runs": int(execution_metadata.get("runs", 0)),
        "wall_seconds": int(execution_metadata.get("wall_seconds", 0)),
        "crashes_total": int(execution_metadata.get("crashes_total", 0)),
        "crashes_matched": int(execution_metadata.get("crashes_matched", 0)),
    }
    for extra_key in (
        "candidate_source",
        "crash_logs_scanned",
        "seeded_run_completed",
        "witness_run_completed",
        "execution_completed",
        "setup_failed",
        "execution_mode",
        "remote_host",
        "witness_source",
    ):
        if extra_key in execution_metadata:
            execution[extra_key] = execution_metadata[extra_key]

    return {
        "candidate_id": candidate_payload.get("candidate_id", ""),
        "verdict": match_result["verdict"],
        "confidence": match_result["confidence"],
        "evidence": match_result["evidence"],
        "execution": execution,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def emit_verdict(
    *,
    output_dir: str | Path,
    candidate_path: str | Path,
    execution_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    candidate_path = Path(candidate_path)
    candidate_payload = load_candidate_record(candidate_path)
    execution_metadata = dict(execution_metadata or {})
    execution_metadata["candidate_source"] = str(candidate_path)

    crash_logs = collect_crash_logs(output_dir)
    execution_metadata["crashes_total"] = len(crash_logs)
    execution_metadata["crash_logs_scanned"] = [str(path) for path in crash_logs]

    best_match: dict[str, Any] | None = None
    matched_count = 0
    for crash_log in crash_logs:
        parsed_crash = parse_crash_file(crash_log)
        match_result = match_candidate(parsed_crash, candidate_payload, execution_metadata)
        if match_result["verdict"] == "CONFIRMED":
            matched_count += 1
        evidence = dict(match_result["evidence"])
        evidence["crash_log"] = str(crash_log)
        match_result = dict(match_result)
        match_result["evidence"] = evidence
        if best_match is None or _verdict_priority(match_result) > _verdict_priority(best_match):
            best_match = match_result

    execution_metadata["crashes_matched"] = matched_count
    if best_match is None:
        best_match = match_candidate(None, candidate_payload, execution_metadata)

    verdict_record = build_verdict_record(candidate_payload, best_match, execution_metadata)
    verdict_path = output_dir / "verdict.json"
    verdict_path.parent.mkdir(parents=True, exist_ok=True)
    verdict_path.write_text(json.dumps(verdict_record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return verdict_record


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Emit a candidate verdict from seeded fuzz output")
    parser.add_argument("--output-dir", required=True, help="Path to the seeded fuzz output directory")
    parser.add_argument("--candidate", help="Explicit candidate.json path")
    parser.add_argument("--seed-workdir", help="Seed workdir used for the run")
    parser.add_argument("--bridge-root", help="uaf-bridge root for candidate lookup")
    parser.add_argument("--wall-seconds", type=int, default=0, help="Observed wall-clock runtime in seconds")
    parser.add_argument("--runs", type=int, default=0, help="Observed run count if known")
    parser.add_argument("--execution-completed", action="store_true", help="Mark a non-fuzz execution as completed")
    parser.add_argument("--witness-run-completed", action="store_true", help="Mark a witness execution as completed")
    parser.add_argument("--setup-failed", action="store_true", help="Mark setup/execution as failing before the path ran")
    parser.add_argument("--execution-mode", help="Execution mode label, for example witness_remote")
    parser.add_argument("--remote-host", help="SSH target host used for the execution")
    parser.add_argument("--witness-source", help="Source witness.syz path used for the execution")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    candidate_path = resolve_candidate_path(
        candidate_path=args.candidate,
        seed_workdir=args.seed_workdir,
        bridge_root=args.bridge_root,
    )
    seeded_run_completed = args.execution_mode in (None, "", "seeded_fuzz")
    verdict = emit_verdict(
        output_dir=args.output_dir,
        candidate_path=candidate_path,
        execution_metadata={
            "runs": args.runs,
            "wall_seconds": args.wall_seconds,
            "seeded_run_completed": seeded_run_completed,
            "execution_completed": args.execution_completed,
            "witness_run_completed": args.witness_run_completed,
            "setup_failed": args.setup_failed,
            "execution_mode": args.execution_mode,
            "remote_host": args.remote_host,
            "witness_source": args.witness_source,
        },
    )
    print(
        f"Verdict: {verdict['verdict']} ({verdict['confidence']}) "
        f"for {verdict['candidate_id']}"
    )
    print(f"Verdict written to: {Path(args.output_dir) / 'verdict.json'}")


if __name__ == "__main__":
    main()
