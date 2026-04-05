#!/usr/bin/env python3
"""Real-runtime io_uring validation lane for ordinary arm64 Linux VMs.

This module executes synthesized seed programs with syz-execprog, captures runtime
signals, emits per-seed triage reports, and writes aggregate machine-readable evidence.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shlex
import subprocess
import sys
import time
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from orchestrator.score import _score_phase_progress, _score_prefix, _score_resource_chain
from pack_registry import resolve_target_manifest
from triage.match_candidate import match_crash
from triage.parse_kasan import parse_kasan_report
from triage.report import build_triage_report
from triage.io_uring_verdict import classify_io_uring_runtime_verdict
from triage.io_uring_symbols import classify_crash_subsystem_relevance, enrich_crash_match


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    with open(path) as f:
        return json.load(f)


def _write_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def _canonical_seed_calls(seed_path: pathlib.Path, manifest: dict[str, Any]) -> list[str]:
    reverse: dict[str, str] = {}
    for canonical_call, syz_line in manifest.get("syz_call_map", {}).items():
        if not isinstance(canonical_call, str) or not isinstance(syz_line, str):
            continue
        normalized = syz_line.strip()
        if "=" in normalized:
            normalized = normalized.split("=", 1)[1].strip()
        call_name = normalized.split("(", 1)[0].strip()
        if call_name and call_name not in reverse:
            reverse[call_name] = canonical_call

    canonical_calls: list[str] = []
    for line in seed_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            stripped = stripped.split("=", 1)[1].strip()
        call_name = stripped.split("(", 1)[0].strip()
        if call_name in reverse:
            canonical_calls.append(reverse[call_name])
        else:
            canonical_calls.append(call_name)
    return canonical_calls


def _run_cmd(cmd: list[str], timeout_sec: int) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
        return {
            "ok": True,
            "timed_out": False,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "duration_sec": round(time.monotonic() - started, 3),
            "error": None,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "timed_out": True,
            "returncode": None,
            "stdout": (exc.stdout or "") if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "") if isinstance(exc.stderr, str) else "",
            "duration_sec": round(time.monotonic() - started, 3),
            "error": f"timeout after {timeout_sec}s",
        }
    except OSError as exc:
        return {
            "ok": False,
            "timed_out": False,
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "duration_sec": round(time.monotonic() - started, 3),
            "error": str(exc),
        }


def _run_execprog(
    syz_execprog: pathlib.Path,
    syz_executor: pathlib.Path,
    seed: pathlib.Path,
    timeout_sec: int,
    threaded: bool,
    procs: int,
) -> dict[str, Any]:
    cmd = [
        str(syz_execprog),
        f"-executor={syz_executor}",
        "-repeat=0",
        f"-procs={procs}",
        f"-threaded={1 if threaded else 0}",
        str(seed),
    ]
    result = _run_cmd(cmd, timeout_sec)
    result["cmd"] = cmd
    return result


def _collect_dmesg(dmesg_cmd: list[str]) -> dict[str, Any]:
    result = _run_cmd(dmesg_cmd, timeout_sec=20)
    if result["ok"]:
        return {
            "ok": True,
            "text": result["stdout"],
            "error": None,
            "returncode": result["returncode"],
        }
    return {
        "ok": False,
        "text": "",
        "error": result["error"],
        "returncode": result["returncode"],
    }


def _phase_name(progress: float) -> str:
    if progress >= 1.0:
        return "trigger"
    if progress >= 0.66:
        return "configure"
    if progress >= 0.33:
        return "bootstrap"
    return "unknown"


def run_io_uring_runtime_lane(
    *,
    state_model_path: pathlib.Path,
    target_profile_path: pathlib.Path,
    seeds_dir: pathlib.Path,
    out_dir: pathlib.Path,
    syz_execprog: pathlib.Path,
    syz_executor: pathlib.Path,
    dmesg_cmd: list[str] | None = None,
    timeout_sec: int = 60,
    threaded: bool = True,
    procs: int = 1,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    seed_runs_dir = out_dir / "seed_runs"
    seed_runs_dir.mkdir(parents=True, exist_ok=True)

    state_model = _load_json(state_model_path)
    target_profile = _load_json(target_profile_path)

    if state_model.get("subsystem") != "io_uring":
        raise ValueError(f"io_uring runtime lane requires io_uring state model; got {state_model.get('subsystem')}")

    manifest = resolve_target_manifest(
        subsystem=state_model.get("subsystem"),
        target_family=state_model.get("target_family"),
    )

    dmesg_cmd = dmesg_cmd or ["dmesg"]

    seeds = sorted(seeds_dir.glob("*.prog"))
    if not seeds:
        raise ValueError(f"no .prog seeds found in {seeds_dir}")

    trace_items: list[dict[str, Any]] = []
    triage_reports: list[dict[str, Any]] = []

    for seed in seeds:
        seed_out = seed_runs_dir / seed.stem
        seed_out.mkdir(parents=True, exist_ok=True)

        calls = _canonical_seed_calls(seed, manifest)
        prefix_valid = _score_prefix(calls, state_model) == 1.0
        chain_intact = _score_resource_chain(calls, state_model) >= 0.9
        phase_progress = _score_phase_progress(calls, state_model)

        exec_result = _run_execprog(
            syz_execprog=syz_execprog,
            syz_executor=syz_executor,
            seed=seed,
            timeout_sec=timeout_sec,
            threaded=threaded,
            procs=procs,
        )
        dmesg_result = _collect_dmesg(dmesg_cmd)

        (seed_out / "exec_stdout.txt").write_text(exec_result.get("stdout", ""), encoding="utf-8")
        (seed_out / "exec_stderr.txt").write_text(exec_result.get("stderr", ""), encoding="utf-8")
        (seed_out / "dmesg.txt").write_text(dmesg_result.get("text", ""), encoding="utf-8")

        crash_text = dmesg_result.get("text", "")
        triage = build_triage_report(crash_text, target_profile, state_model, calls)
        _write_json(seed_out / "triage_report_v1.json", triage)
        triage_reports.append(triage)

        parsed = parse_kasan_report(crash_text)
        if parsed:
            base_match = match_crash(parsed, target_profile)
            candidate_match = enrich_crash_match(parsed, base_match)
            subsystem_relevance = classify_crash_subsystem_relevance(parsed)
        else:
            candidate_match = {
                "focus_frame_hit": False,
                "focus_file_hit": False,
                "free_use_hint_match": False,
                "uaf_type_match": False,
                "match_score": 0.0,
                "io_uring_enrichment": {
                    "is_io_uring_crash": False,
                    "subsystem_relevance_score": 0.0,
                    "lifecycle_frame_hits": [],
                    "source_file_hits": [],
                    "teardown_frame_hits": [],
                    "use_frame_hits": [],
                    "has_teardown_use_pair": False,
                },
            }
            subsystem_relevance = "unrelated"

        has_enter = "io_uring_enter" in calls
        has_close = "close$io_uring" in calls
        has_register = "io_uring_register$IORING_REGISTER_FILES" in calls

        run_item = {
            "seed": seed.name,
            "returncode": exec_result["returncode"],
            "timed_out": exec_result["timed_out"],
            "duration_sec": exec_result["duration_sec"],
            "exec_ok": exec_result["ok"],
            "phase_reached": _phase_name(phase_progress),
            "phase_progress": phase_progress,
            "prefix_valid": prefix_valid,
            "resource_chain_intact": chain_intact,
            "has_kasan": parsed is not None,
            "triage_verdict": triage["verdict"],
            "candidate_match": candidate_match,
            "subsystem_relevance": subsystem_relevance,
            "io_uring_path_signals": {
                "has_register": has_register,
                "has_enter": has_enter,
                "has_close": has_close,
                "close_enter_overlap_attempted": has_enter and has_close and threaded,
            },
            "outputs": {
                "seed_run_dir": str(seed_out),
                "triage_report": str(seed_out / "triage_report_v1.json"),
            },
            "exec_error": exec_result["error"],
            "dmesg_error": dmesg_result["error"],
        }
        _write_json(seed_out / "seed_run_summary.json", run_item)
        trace_items.append(run_item)

    seeds_executed = sum(1 for item in trace_items if item["exec_ok"])
    timeouts = sum(1 for item in trace_items if item["timed_out"])
    crashes_detected = sum(1 for item in trace_items if item["has_kasan"])
    trigger_phase_reached = sum(1 for item in trace_items if item["phase_reached"] == "trigger")

    execution_trace_summary = {
        "candidate_id": state_model["candidate_id"],
        "subsystem": state_model["subsystem"],
        "seed_count": len(trace_items),
        "seeds_executed": seeds_executed,
        "timeouts": timeouts,
        "crashes_detected": crashes_detected,
        "trigger_phase_reached": trigger_phase_reached,
        "seed_runs": trace_items,
    }

    prefix_valid_count = sum(1 for item in trace_items if item["prefix_valid"])
    preserved_prefix_report = {
        "candidate_id": state_model["candidate_id"],
        "immutable_prefix_len": state_model.get("immutable_prefix_len", 0),
        "seed_count": len(trace_items),
        "prefix_valid_count": prefix_valid_count,
        "prefix_valid_rate": (prefix_valid_count / len(trace_items)) if trace_items else 0.0,
        "violations": [item["seed"] for item in trace_items if not item["prefix_valid"]],
    }

    edge_total = 0
    edge_hit = 0
    for item in trace_items:
        if item["resource_chain_intact"]:
            edge_hit += 1
        edge_total += 1
    edge_coverage_summary = {
        "candidate_id": state_model["candidate_id"],
        "resource_chain_checks": edge_total,
        "resource_chain_intact_count": edge_hit,
        "resource_chain_intact_rate": (edge_hit / edge_total) if edge_total else 0.0,
    }

    overlap_count = sum(1 for item in trace_items if item["io_uring_path_signals"]["close_enter_overlap_attempted"])
    concurrency_window_report = {
        "candidate_id": state_model["candidate_id"],
        "threaded_mode": threaded,
        "overlap_window_attempted": overlap_count > 0,
        "overlap_window_attempt_count": overlap_count,
        "close_and_enter_same_seed_count": overlap_count,
    }

    best_match_score = max((float(item["candidate_match"]["match_score"]) for item in trace_items), default=0.0)
    any_uaf_type = any(bool(item["candidate_match"]["uaf_type_match"]) for item in trace_items)

    # Subsystem relevance aggregation
    relevance_counts: dict[str, int] = {}
    for item in trace_items:
        rel = item.get("subsystem_relevance", "unrelated")
        relevance_counts[rel] = relevance_counts.get(rel, 0) + 1

    best_subsystem_score = 0.0
    for item in trace_items:
        enrichment = item.get("candidate_match", {}).get("io_uring_enrichment", {})
        score = float(enrichment.get("subsystem_relevance_score", 0.0))
        if score > best_subsystem_score:
            best_subsystem_score = score

    alignment = {
        "candidate_id": state_model["candidate_id"],
        "best_match_score": best_match_score,
        "any_uaf_type_match": any_uaf_type,
        "focus_frame_hits": sum(1 for item in trace_items if item["candidate_match"]["focus_frame_hit"]),
        "focus_file_hits": sum(1 for item in trace_items if item["candidate_match"]["focus_file_hit"]),
        "free_use_hint_hits": sum(1 for item in trace_items if item["candidate_match"]["free_use_hint_match"]),
        "triage_verdicts": sorted(set(item["triage_verdict"] for item in trace_items)),
        "subsystem_relevance_counts": relevance_counts,
        "best_subsystem_relevance_score": round(best_subsystem_score, 3),
    }

    runtime_verdict = classify_io_uring_runtime_verdict(
        execution_trace_summary=execution_trace_summary,
        candidate_alignment_report=alignment,
        preserved_prefix_report=preserved_prefix_report,
        concurrency_window_report=concurrency_window_report,
    )

    _write_json(out_dir / "execution_trace_summary.json", execution_trace_summary)
    _write_json(out_dir / "preserved_prefix_report.json", preserved_prefix_report)
    _write_json(out_dir / "edge_coverage_summary.json", edge_coverage_summary)
    _write_json(out_dir / "concurrency_window_report.json", concurrency_window_report)
    _write_json(out_dir / "candidate_alignment_report.json", alignment)
    _write_json(out_dir / "runtime_verdict.json", runtime_verdict)

    return {
        "execution_trace_summary": execution_trace_summary,
        "preserved_prefix_report": preserved_prefix_report,
        "edge_coverage_summary": edge_coverage_summary,
        "concurrency_window_report": concurrency_window_report,
        "candidate_alignment_report": alignment,
        "runtime_verdict": runtime_verdict,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run real io_uring runtime validation lane")
    parser.add_argument("--state-model", required=True, help="Path to state_model_v1.json")
    parser.add_argument("--target-profile", required=True, help="Path to target_profile.json")
    parser.add_argument("--seeds-dir", required=True, help="Directory with seed_*.prog")
    parser.add_argument("--syz-execprog", required=True, help="Path to syz-execprog binary")
    parser.add_argument("--syz-executor", required=True, help="Path to syz-executor binary")
    parser.add_argument("--out-dir", required=True, help="Output directory for runtime evidence")
    parser.add_argument("--timeout-sec", type=int, default=60, help="Per-seed execution timeout")
    parser.add_argument("--threaded", action="store_true", default=False, help="Run syz-execprog with threaded mode")
    parser.add_argument("--procs", type=int, default=1, help="syz-execprog -procs value")
    parser.add_argument(
        "--dmesg-cmd",
        default="dmesg",
        help="Command used to collect kernel log (example: 'sudo dmesg')",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    dmesg_cmd = shlex.split(args.dmesg_cmd)
    summary = run_io_uring_runtime_lane(
        state_model_path=pathlib.Path(args.state_model),
        target_profile_path=pathlib.Path(args.target_profile),
        seeds_dir=pathlib.Path(args.seeds_dir),
        out_dir=pathlib.Path(args.out_dir),
        syz_execprog=pathlib.Path(args.syz_execprog),
        syz_executor=pathlib.Path(args.syz_executor),
        dmesg_cmd=dmesg_cmd,
        timeout_sec=args.timeout_sec,
        threaded=args.threaded,
        procs=args.procs,
    )

    verdict = summary["runtime_verdict"]["verdict_class"]
    print(f"io_uring runtime verdict: {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
