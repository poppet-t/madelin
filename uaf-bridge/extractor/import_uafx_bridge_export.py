"""Import a richer UAFX bridge export into canonical candidate.json."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from common.cli import print_cli_error
from common.io import load_json, write_json
from common.schema_validation import validate_candidate
from extractor.normalize_candidate import (
    SCHEMA_VERSION,
    build_constraints,
    build_entries,
    load_manual_map,
    normalize_location,
)
from mapping.target_registry import target_context


def _build_candidate_id(export_payload: dict[str, Any]) -> str:
    canonical = json.dumps(export_payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"cand_{digest[:16]}"


def _normalize_flow(export_payload: dict[str, Any]) -> str:
    flow = export_payload.get("flow")
    return flow if isinstance(flow, str) and flow in {"Seq", "Con", "Unknown"} else "Unknown"


def _entry_candidates_from_export(export_payload: dict[str, Any]) -> list[dict[str, Any]]:
    entry_summary = export_payload.get("entry_summary")
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    if isinstance(entry_summary, dict):
        raw_candidates = entry_summary.get("entry_candidates", [])
        if isinstance(raw_candidates, list):
            for candidate in raw_candidates:
                if not isinstance(candidate, dict):
                    continue
                entry_func = candidate.get("entry_func")
                if not isinstance(entry_func, str) or entry_func in seen:
                    continue
                seen.add(entry_func)
                candidates.append(
                    {
                        "confidence": candidate.get("confidence") if isinstance(candidate.get("confidence"), str) else "unknown",
                        "entry_func": entry_func,
                        "entry_kind_hint": candidate.get("entry_kind_hint") if isinstance(candidate.get("entry_kind_hint"), str) else None,
                    }
                )
        raw_top_entries = entry_summary.get("top_entries", [])
        if isinstance(raw_top_entries, list):
            for entry_func in raw_top_entries:
                if isinstance(entry_func, str) and entry_func not in seen:
                    seen.add(entry_func)
                    candidates.append({"confidence": "heuristic", "entry_func": entry_func, "entry_kind_hint": None})
    return candidates


def _heuristic_predicates(export_payload: dict[str, Any]) -> list[str]:
    constraint_summary = export_payload.get("constraint_summary")
    names: list[str] = []
    if not isinstance(constraint_summary, dict):
        return names
    predicates = constraint_summary.get("predicates", [])
    if not isinstance(predicates, list):
        return names
    for predicate in predicates:
        if not isinstance(predicate, dict):
            continue
        name = predicate.get("name")
        scope = predicate.get("scope")
        if isinstance(name, str) and scope == "heuristic":
            names.append(name)
    return sorted(names)


def _analysis_context_from_export(export_payload: dict[str, Any]) -> dict[str, str]:
    raw_warning = export_payload.get("raw_warning") if isinstance(export_payload.get("raw_warning"), dict) else {}
    return target_context(
        kernel_area=export_payload.get("kernel_area") if isinstance(export_payload.get("kernel_area"), str) else None,
        subsystem=export_payload.get("subsystem") if isinstance(export_payload.get("subsystem"), str) else raw_warning.get("subsystem") if isinstance(raw_warning.get("subsystem"), str) else None,
        target_family=export_payload.get("target_family") if isinstance(export_payload.get("target_family"), str) else None,
        arch=export_payload.get("arch") if isinstance(export_payload.get("arch"), str) else raw_warning.get("arch") if isinstance(raw_warning.get("arch"), str) else None,
        default_pack="kvm",
    )


def import_uafx_bridge_export(export_payload: dict[str, Any], raw_file: str | None = None) -> dict[str, Any]:
    loc0 = normalize_location(export_payload.get("loc0"))
    loc1 = normalize_location(export_payload.get("loc1"))
    flow = _normalize_flow(export_payload)
    manual_map = load_manual_map()
    analysis_context = _analysis_context_from_export(export_payload)
    entry_candidates = _entry_candidates_from_export(export_payload)
    entries, entry_summary = build_entries(entry_candidates, manual_map, analysis_context=analysis_context)

    constraint_summary = export_payload.get("constraint_summary") if isinstance(export_payload.get("constraint_summary"), dict) else {}
    synthesized_warning = {
        "constraints": {
            "min_threads": 2 if flow == "Con" else 1,
            "partial_order": constraint_summary.get("partial_order", []),
            "predicates": constraint_summary.get("predicates", []),
            "same_object": constraint_summary.get("same_object"),
        },
        "flow": flow,
        "loc0": loc0,
        "loc1": loc1,
        "source": {
            "raw_file": raw_file,
            "tool": "uafx-bridge-export",
            "version": export_payload.get("export_version") if isinstance(export_payload.get("export_version"), str) else None,
        },
        "warning_id": export_payload.get("warning_id"),
    }
    constraints = build_constraints(synthesized_warning, flow)

    unsupported_reasons = [
        reason
        for entry in entries
        for reason in entry.get("unsupported_reasons", [])
        if isinstance(reason, str)
    ]
    heuristic_predicates = _heuristic_predicates(export_payload)
    candidate = {
        "analysis_context": analysis_context,
        "candidate_id": _build_candidate_id(export_payload),
        "constraints": constraints,
        "entries": entries,
        "flow": flow,
        "loc0": loc0,
        "loc1": loc1,
        "provenance": {
            "normalizer": "extractor.import_uafx_bridge_export",
            "raw_warning_sha256_prefix": hashlib.sha256(
                json.dumps(export_payload.get("raw_warning", {}), sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()[:16],
            "warning_id": export_payload.get("warning_id") if isinstance(export_payload.get("warning_id"), str) else None,
        },
        "raw_warning": export_payload.get("raw_warning") if isinstance(export_payload.get("raw_warning"), dict) else {},
        "schema_version": SCHEMA_VERSION,
        "source": {
            "raw_file": raw_file,
            "tool": f"{export_payload.get('source_tool', 'uafx')}-bridge-import",
            "version": export_payload.get("export_version") if isinstance(export_payload.get("export_version"), str) else None,
        },
        "status": {
            "grounded_entries": entry_summary["grounded_entries"],
            "heuristic_entries": entry_summary["heuristic_entries"],
            "mapping_confidence": entry_summary["mapping_confidence"],
            "ready_for_smt": any(entry["supported"] and entry["syscall_templates"] for entry in entries),
            "supported": any(entry["supported"] and entry["syscall_templates"] for entry in entries),
            "unsupported_entries": entry_summary["unsupported_entries"],
            "unsupported_reasons": unsupported_reasons + [f"heuristic predicate preserved: {name}" for name in heuristic_predicates],
        },
    }
    validate_candidate(candidate)
    return candidate


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import a richer UAFX bridge export into candidate.json")
    parser.add_argument("--input", required=True, help="Path to UAFX bridge export JSON")
    parser.add_argument("--output", required=True, help="Path to output candidate.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    candidate_id: str | None = None
    try:
        input_path = Path(args.input)
        export_payload = load_json(input_path)
        candidate = import_uafx_bridge_export(export_payload, raw_file=str(input_path))
        candidate_id = candidate.get("candidate_id") if isinstance(candidate.get("candidate_id"), str) else None
        write_json(Path(args.output), candidate)
    except Exception as exc:
        return print_cli_error("import_uafx_bridge_export", exc, candidate_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
