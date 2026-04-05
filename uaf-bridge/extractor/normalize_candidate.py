"""Normalize static warning JSON into the canonical candidate schema."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from common.cli import print_cli_error
from common.io import load_json, write_json
from common.schema_validation import validate_candidate
from mapping.entry_classifier import classify_entry, infer_entry_functions
from mapping.syscall_templates import generate_templates
from mapping.target_registry import load_target_manifests, target_context

SCHEMA_VERSION = "candidate/v1"
DEFAULT_EVENTS: list[str] = ["init_resource", "escape", "free", "fetch", "use", "cleanup"]
DEFAULT_PARTIAL_ORDER: list[dict[str, str]] = [
    {
        "before": "escape",
        "after": "fetch",
        "reason": "Pointer must escape before later fetch/use chain.",
    },
    {
        "before": "free",
        "after": "use",
        "reason": "Use-after-free requires free to occur before use.",
    },
]
VALID_FLOWS = {"Seq", "Con", "Unknown"}
MANUAL_MAP_PATH = Path(__file__).resolve().parents[1] / "mapping" / "manual_driver_map.yaml"


def normalize_location(raw_loc: Any) -> dict[str, Any]:
    if not isinstance(raw_loc, dict):
        raw_loc = {}

    context = raw_loc.get("context", [])
    context_list = [str(item) for item in context] if isinstance(context, list) else []

    line = raw_loc.get("line")
    line_value = line if isinstance(line, int) and line >= 0 else None

    function = raw_loc.get("function")
    function_value = function if isinstance(function, str) else None

    source_file = raw_loc.get("file")
    file_value = source_file if isinstance(source_file, str) else None

    return {
        "context": context_list,
        "file": file_value,
        "function": function_value,
        "line": line_value,
    }


def normalize_flow(raw_warning: dict[str, Any]) -> str:
    flow = raw_warning.get("flow")
    if isinstance(flow, str) and flow in VALID_FLOWS:
        return flow
    return "Unknown"


def build_candidate_id(raw_warning: dict[str, Any]) -> str:
    canonical = json.dumps(raw_warning, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"cand_{digest[:16]}"


def load_manual_map(path: Path = MANUAL_MAP_PATH) -> dict[str, dict[str, Any]]:
    data = load_json(path)
    entries = data.get("manual_entries", {}) if isinstance(data, dict) else {}
    if not isinstance(entries, dict):
        raise ValueError(f"manual_entries must be an object in {path}")
    return {str(k): v for k, v in entries.items() if isinstance(v, dict)}


def pick_min_threads(raw_warning: dict[str, Any], flow: str) -> int:
    constraints = raw_warning.get("constraints")
    if isinstance(constraints, dict):
        raw_min_threads = constraints.get("min_threads")
        if isinstance(raw_min_threads, int) and raw_min_threads >= 1:
            return raw_min_threads
    return 2 if flow == "Con" else 1


def extract_predicates(raw_warning: dict[str, Any]) -> list[dict[str, str]]:
    constraints = raw_warning.get("constraints")
    if not isinstance(constraints, dict):
        return []

    raw_predicates = constraints.get("predicates", [])
    if not isinstance(raw_predicates, list):
        return []

    normalized: list[dict[str, str]] = []
    for pred in raw_predicates:
        if not isinstance(pred, dict):
            continue
        name = pred.get("name")
        must_hold_at = pred.get("must_hold_at")
        scope = pred.get("scope")
        if isinstance(name, str) and isinstance(must_hold_at, str) and isinstance(scope, str):
            normalized.append({"must_hold_at": must_hold_at, "name": name, "scope": scope})
    return normalized


def extract_same_object(raw_warning: dict[str, Any]) -> bool | None:
    constraints = raw_warning.get("constraints")
    if not isinstance(constraints, dict):
        return None
    same_object = constraints.get("same_object")
    if isinstance(same_object, bool):
        return same_object
    return None


def dedupe_partial_order(edges: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, str]] = []
    for edge in edges:
        key = (edge["before"], edge["after"], edge["reason"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(edge)
    return deduped


def build_constraints(raw_warning: dict[str, Any], flow: str) -> dict[str, Any]:
    events = list(DEFAULT_EVENTS)
    raw_constraints = raw_warning.get("constraints") if isinstance(raw_warning.get("constraints"), dict) else {}

    if isinstance(raw_constraints, dict):
        raw_events = raw_constraints.get("events")
        if isinstance(raw_events, list):
            filtered = [str(event) for event in raw_events if isinstance(event, str)]
            if filtered:
                events = list(dict.fromkeys(filtered))

    edges: list[dict[str, str]] = list(DEFAULT_PARTIAL_ORDER)
    if isinstance(raw_constraints, dict):
        raw_edges = raw_constraints.get("partial_order")
        if isinstance(raw_edges, list):
            for edge in raw_edges:
                if not isinstance(edge, dict):
                    continue
                before = edge.get("before")
                after = edge.get("after")
                reason = edge.get("reason")
                if isinstance(before, str) and isinstance(after, str) and isinstance(reason, str):
                    edges.append({"after": after, "before": before, "reason": reason})

    return {
        "events": events,
        "min_threads": pick_min_threads(raw_warning, flow),
        "partial_order": dedupe_partial_order(edges),
        "predicates": extract_predicates(raw_warning),
        "same_object": extract_same_object(raw_warning),
    }


def _recognized_subsystem(subsystem: str | None) -> bool:
    return isinstance(subsystem, str) and subsystem in load_target_manifests()


def _analysis_context(raw_warning: dict[str, Any]) -> dict[str, str]:
    metadata = raw_warning.get("metadata") if isinstance(raw_warning.get("metadata"), dict) else {}
    kernel_area = raw_warning.get("kernel_area") if isinstance(raw_warning.get("kernel_area"), str) else metadata.get("kernel_area")
    subsystem = raw_warning.get("subsystem") if isinstance(raw_warning.get("subsystem"), str) else metadata.get("subsystem")
    target_family = raw_warning.get("target_family") if isinstance(raw_warning.get("target_family"), str) else metadata.get("target_family")
    arch = raw_warning.get("arch") if isinstance(raw_warning.get("arch"), str) else metadata.get("arch")

    if kernel_area or _recognized_subsystem(subsystem) or target_family:
        return target_context(kernel_area=kernel_area, subsystem=subsystem, target_family=target_family, arch=arch)

    resolved_arch = arch if isinstance(arch, str) and arch else "unknown"
    resolved_subsystem = subsystem if isinstance(subsystem, str) and subsystem else "unknown"
    resolved_target = target_family if isinstance(target_family, str) and target_family else f"{resolved_subsystem}-{resolved_arch}-generic"
    resolved_area = kernel_area if isinstance(kernel_area, str) and kernel_area else "unknown"
    return {
        "arch": resolved_arch,
        "kernel_area": resolved_area,
        "subsystem": resolved_subsystem,
        "target_family": resolved_target,
    }


def _normalize_entry_candidates(raw_warning: dict[str, Any], loc0: dict[str, Any], loc1: dict[str, Any]) -> list[dict[str, Any]]:
    raw_candidates = raw_warning.get("entry_candidates")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()

    if isinstance(raw_candidates, list):
        for candidate in raw_candidates:
            if not isinstance(candidate, dict):
                continue
            entry_func = candidate.get("entry_func") if isinstance(candidate.get("entry_func"), str) else candidate.get("function")
            if not isinstance(entry_func, str) or entry_func in seen:
                continue
            seen.add(entry_func)
            normalized.append(
                {
                    "confidence": candidate.get("confidence") if isinstance(candidate.get("confidence"), str) else "unknown",
                    "entry_func": entry_func,
                    "entry_kind_hint": candidate.get("entry_kind_hint") if isinstance(candidate.get("entry_kind_hint"), str) else candidate.get("kind_hint"),
                }
            )

    if normalized:
        return normalized

    for entry_func in infer_entry_functions(loc0["context"], loc1["context"]):
        normalized.append({"confidence": "heuristic", "entry_func": entry_func, "entry_kind_hint": None})
    return normalized


def _build_entry_record(entry_candidate: str | dict[str, Any], manual_map: dict[str, dict[str, Any]], analysis_context: dict[str, str]) -> dict[str, Any]:
    if isinstance(entry_candidate, dict):
        entry_func = entry_candidate.get("entry_func")
        entry_kind_hint = entry_candidate.get("entry_kind_hint")
        confidence = entry_candidate.get("confidence") if isinstance(entry_candidate.get("confidence"), str) else None
    else:
        entry_func = entry_candidate
        entry_kind_hint = None
        confidence = None

    if not isinstance(entry_func, str):
        raise ValueError("entry candidate is missing entry_func")

    manual_record = manual_map.get(entry_func)
    grounded: dict[str, Any] = {"entry_func": entry_func}
    heuristic: dict[str, Any] = {}
    unsupported_reasons: list[str] = []

    if manual_record is not None:
        entry_kind = str(manual_record.get("entry_kind", classify_entry(entry_func, entry_kind_hint)))
        grounded["entry_kind"] = entry_kind
        grounded["mapping_source"] = "manual"
        if isinstance(entry_kind_hint, str):
            grounded["entry_kind_hint"] = entry_kind_hint
    else:
        entry_kind = classify_entry(entry_func, entry_kind_hint)
        if isinstance(entry_kind_hint, str):
            heuristic["entry_kind_hint"] = entry_kind_hint
            heuristic["mapping_source"] = "export_hint"
        else:
            heuristic["mapping_source"] = "heuristic"

    supported = entry_kind != "unknown"
    if not supported:
        unsupported_reasons.append(f"unsupported entry class for function '{entry_func}'")

    templates = generate_templates(entry_func, entry_kind, analysis_context=analysis_context) if supported else []
    if supported and not templates:
        unsupported_reasons.append(
            f"no syscall templates for entry kind '{entry_kind}' in subsystem '{analysis_context.get('subsystem', 'unknown')}'"
        )

    support_level = "grounded" if manual_record is not None else "heuristic" if supported else "unsupported"
    if confidence is not None:
        if support_level == "grounded":
            grounded["confidence"] = confidence
        else:
            heuristic["confidence"] = confidence

    return {
        "entry_func": entry_func,
        "entry_kind": entry_kind,
        "grounded": grounded,
        "heuristic": heuristic,
        "supported": supported,
        "support_level": support_level,
        "unsupported_reasons": unsupported_reasons,
        "syscall_templates": templates,
    }


def build_entries(
    entry_candidates: list[str] | list[dict[str, Any]],
    manual_map: dict[str, dict[str, Any]],
    analysis_context: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    context = analysis_context or {
        "arch": "unknown",
        "kernel_area": "unknown",
        "subsystem": "unknown",
        "target_family": "unknown",
    }
    entries = [_build_entry_record(entry_candidate, manual_map, context) for entry_candidate in entry_candidates]
    grounded_entries = [entry["entry_func"] for entry in entries if entry["support_level"] == "grounded"]
    heuristic_entries = [entry["entry_func"] for entry in entries if entry["support_level"] == "heuristic"]
    unsupported_entries = [entry["entry_func"] for entry in entries if not entry["supported"]]

    if grounded_entries:
        mapping_confidence = "manual"
    elif heuristic_entries:
        mapping_confidence = "heuristic"
    else:
        mapping_confidence = "unknown"

    return entries, {
        "grounded_entries": grounded_entries,
        "heuristic_entries": heuristic_entries,
        "unsupported_entries": unsupported_entries,
        "mapping_confidence": mapping_confidence,
    }


def normalize_warning(raw_warning: dict[str, Any], raw_file: str | None = None) -> dict[str, Any]:
    loc0 = normalize_location(raw_warning.get("loc0"))
    loc1 = normalize_location(raw_warning.get("loc1"))
    flow = normalize_flow(raw_warning)
    manual_map = load_manual_map()
    analysis_context = _analysis_context(raw_warning)

    entry_candidates = _normalize_entry_candidates(raw_warning, loc0, loc1)
    entries, entry_summary = build_entries(entry_candidates, manual_map, analysis_context=analysis_context)

    source = raw_warning.get("source") if isinstance(raw_warning.get("source"), dict) else {}
    source_tool = source.get("tool") if isinstance(source.get("tool"), str) else "unknown-static-tool"
    source_version = source.get("version") if isinstance(source.get("version"), str) else None
    source_file = raw_file if raw_file is not None else source.get("raw_file") if isinstance(source.get("raw_file"), str) else None

    ready_for_smt = any(entry["supported"] and entry["syscall_templates"] for entry in entries)
    unsupported_reasons = [
        reason
        for entry in entries
        for reason in entry.get("unsupported_reasons", [])
        if isinstance(reason, str)
    ]
    candidate = {
        "analysis_context": analysis_context,
        "candidate_id": build_candidate_id(raw_warning),
        "constraints": build_constraints(raw_warning, flow),
        "entries": entries,
        "flow": flow,
        "loc0": loc0,
        "loc1": loc1,
        "provenance": {
            "normalizer": "extractor.normalize_candidate",
            "raw_warning_sha256_prefix": hashlib.sha256(
                json.dumps(raw_warning, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()[:16],
            "warning_id": raw_warning.get("warning_id") if isinstance(raw_warning.get("warning_id"), str) else None,
        },
        "raw_warning": raw_warning,
        "schema_version": SCHEMA_VERSION,
        "source": {"raw_file": source_file, "tool": source_tool, "version": source_version},
        "status": {
            "grounded_entries": entry_summary["grounded_entries"],
            "heuristic_entries": entry_summary["heuristic_entries"],
            "mapping_confidence": entry_summary["mapping_confidence"],
            "ready_for_smt": ready_for_smt,
            "supported": ready_for_smt,
            "unsupported_entries": entry_summary["unsupported_entries"],
            "unsupported_reasons": unsupported_reasons,
        },
    }
    validate_candidate(candidate)
    return candidate


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Normalize a static warning into candidate.json")
    parser.add_argument("--input", required=True, help="Path to raw warning JSON")
    parser.add_argument("--output", required=True, help="Path to output candidate JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    candidate_id: str | None = None
    try:
        input_path = Path(args.input)
        raw_warning = load_json(input_path)
        candidate = normalize_warning(raw_warning, raw_file=str(input_path))
        candidate_id = candidate.get("candidate_id") if isinstance(candidate.get("candidate_id"), str) else None
        write_json(Path(args.output), candidate)
    except Exception as exc:
        return print_cli_error("normalize_candidate", exc, candidate_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
