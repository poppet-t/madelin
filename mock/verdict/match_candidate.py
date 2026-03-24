from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_candidate_record(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("candidate input must be a JSON object")
    return payload


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _location(payload: dict[str, Any], key: str) -> dict[str, Any]:
    direct = payload.get(key)
    if isinstance(direct, dict):
        return direct

    debug = payload.get("debug")
    if isinstance(debug, dict):
        candidate = debug.get(key)
        if isinstance(candidate, dict):
            return candidate

    raw_warning = payload.get("raw_warning")
    if isinstance(raw_warning, dict):
        fallback_key = "free_site" if key == "loc0" else "use_site"
        candidate = raw_warning.get(fallback_key)
        if isinstance(candidate, dict):
            return candidate

    return {}


def _entry_functions(payload: dict[str, Any]) -> list[str]:
    entry_functions: list[str] = []
    entries = payload.get("entries")
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("entry_func"), str):
                entry_functions.append(entry["entry_func"])

    debug = payload.get("debug")
    if isinstance(debug, dict) and isinstance(debug.get("selected_entry_func"), str):
        entry_functions.append(debug["selected_entry_func"])

    return _dedupe(entry_functions)


def _subsystem_prefix(payload: dict[str, Any], loc0: dict[str, Any], loc1: dict[str, Any]) -> str | None:
    analysis_context = payload.get("analysis_context")
    if isinstance(analysis_context, dict) and isinstance(analysis_context.get("kernel_area"), str):
        return analysis_context["kernel_area"]

    raw_warning = payload.get("raw_warning")
    if isinstance(raw_warning, dict) and isinstance(raw_warning.get("kernel_area"), str):
        return raw_warning["kernel_area"]

    for location in (loc0, loc1):
        file_name = location.get("file")
        if isinstance(file_name, str) and "/" in file_name:
            return file_name.rsplit("/", 1)[0]
    return None


def normalize_candidate_record(payload: dict[str, Any]) -> dict[str, Any]:
    loc0 = _location(payload, "loc0")
    loc1 = _location(payload, "loc1")
    return {
        "candidate_id": str(payload.get("candidate_id", "")),
        "loc0": loc0,
        "loc1": loc1,
        "entry_functions": _entry_functions(payload),
        "subsystem_prefix": _subsystem_prefix(payload, loc0, loc1),
    }


def _frame_function_names(frames: list[dict[str, Any]]) -> set[str]:
    return {
        str(frame["function"])
        for frame in frames
        if isinstance(frame, dict) and isinstance(frame.get("function"), str)
    }


def _frames_with_function(frames: list[dict[str, Any]], function_name: str) -> list[dict[str, Any]]:
    return [frame for frame in frames if frame.get("function") == function_name]


def _subsystem_matches(parsed_crash: dict[str, Any], subsystem_prefix: str | None) -> bool:
    if not subsystem_prefix:
        return False
    all_frames = [
        *parsed_crash.get("stack_frames", []),
        *parsed_crash.get("free_stack", []),
        *parsed_crash.get("alloc_stack", []),
    ]
    for frame in all_frames:
        if isinstance(frame, dict) and isinstance(frame.get("file"), str):
            if frame["file"].startswith(subsystem_prefix):
                return True
    return False


def _has_crash_content(parsed_crash: dict[str, Any] | None) -> bool:
    if parsed_crash is None:
        return False
    return bool(
        parsed_crash.get("crash_type")
        or parsed_crash.get("stack_frames")
        or parsed_crash.get("free_stack")
        or parsed_crash.get("alloc_stack")
        or parsed_crash.get("raw")
    )


def _execution_completed(execution_metadata: dict[str, Any]) -> bool:
    return bool(
        execution_metadata.get("execution_completed")
        or execution_metadata.get("witness_run_completed")
        or execution_metadata.get("seeded_run_completed")
    )


def match_candidate(
    parsed_crash: dict[str, Any] | None,
    candidate_payload: dict[str, Any],
    execution_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    execution_metadata = execution_metadata or {}
    candidate = normalize_candidate_record(candidate_payload)
    parsed_crash = parsed_crash or {
        "crash_type": None,
        "stack_frames": [],
        "free_stack": [],
        "alloc_stack": [],
        "raw": "",
    }

    loc0_function = candidate["loc0"].get("function")
    loc1_function = candidate["loc1"].get("function")
    stack_frames = parsed_crash.get("stack_frames", [])
    free_stack = parsed_crash.get("free_stack", [])
    crash_type = parsed_crash.get("crash_type")

    loc0_match = isinstance(loc0_function, str) and bool(_frames_with_function(free_stack, loc0_function))
    loc1_match = isinstance(loc1_function, str) and bool(_frames_with_function(stack_frames, loc1_function))
    crash_type_match = crash_type == "use-after-free"
    subsystem_match = _subsystem_matches(parsed_crash, candidate["subsystem_prefix"])

    matched_frames: list[dict[str, Any]] = []
    if isinstance(loc0_function, str):
        matched_frames.extend(
            {"section": "free_stack", **frame} for frame in _frames_with_function(free_stack, loc0_function)
        )
    if isinstance(loc1_function, str):
        matched_frames.extend(
            {"section": "stack_frames", **frame} for frame in _frames_with_function(stack_frames, loc1_function)
        )
    stack_function_names = _frame_function_names(stack_frames)
    for entry_function in candidate["entry_functions"]:
        if entry_function in stack_function_names:
            matched_frames.append({"section": "stack_frames", "function": entry_function})

    evidence = {
        "loc0_match": loc0_match,
        "loc1_match": loc1_match,
        "crash_type_match": crash_type_match,
        "subsystem_match": subsystem_match,
        "matched_frames": matched_frames,
        "entry_functions": candidate["entry_functions"],
    }

    if execution_metadata.get("setup_failed"):
        verdict = "SETUP_FAILED"
        confidence = "medium"
    elif _has_crash_content(parsed_crash):
        if crash_type_match and loc0_match and loc1_match:
            verdict = "CONFIRMED"
            confidence = "high"
        else:
            verdict = "UNRELATED_CRASH"
            confidence = "medium" if subsystem_match else "low"
    elif execution_metadata.get("timing_window_entered"):
        verdict = "TIMING_INCONCLUSIVE"
        confidence = "medium"
    elif execution_metadata.get("candidate_reached") is False or execution_metadata.get("path_infeasible"):
        verdict = "PATH_INFEASIBLE"
        confidence = "low"
    elif _execution_completed(execution_metadata):
        verdict = "REACHED_NO_CRASH"
        confidence = "low"
    else:
        verdict = "PATH_INFEASIBLE"
        confidence = "low"

    return {
        "verdict": verdict,
        "confidence": confidence,
        "evidence": evidence,
    }
