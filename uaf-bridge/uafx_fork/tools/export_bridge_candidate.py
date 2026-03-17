"""Post-process one raw UAFX warning into the richer bridge export shape.

This is written as a narrow integration stub for one KVM/arm64 candidate family.
It is intended to be copied into a real UAFX fork or used as a standalone
post-processor around existing raw UAFX warning JSON output.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common.io import load_json, write_json

EXPORT_VERSION = "0.1"


def _normalize_location(raw_loc: Any) -> dict[str, Any]:
    if not isinstance(raw_loc, dict):
        raw_loc = {}
    context = raw_loc.get("context", [])
    return {
        "context": [str(item) for item in context] if isinstance(context, list) else [],
        "file": raw_loc.get("file") if isinstance(raw_loc.get("file"), str) else None,
        "function": raw_loc.get("function") if isinstance(raw_loc.get("function"), str) else None,
        "line": raw_loc.get("line") if isinstance(raw_loc.get("line"), int) else None,
    }


def _entry_summary(raw_warning: dict[str, Any], loc0: dict[str, Any], loc1: dict[str, Any]) -> dict[str, Any]:
    raw_candidates = raw_warning.get("entry_candidates", [])
    entry_candidates: list[dict[str, Any]] = []
    top_entries: list[str] = []

    if isinstance(raw_candidates, list):
        for candidate in raw_candidates:
            if not isinstance(candidate, dict):
                continue
            entry_func = candidate.get("function")
            if not isinstance(entry_func, str):
                continue
            top_entries.append(entry_func)
            entry_candidates.append(
                {
                    "confidence": candidate.get("confidence") if isinstance(candidate.get("confidence"), str) else "unknown",
                    "entry_func": entry_func,
                    "entry_kind_hint": candidate.get("kind_hint") if isinstance(candidate.get("kind_hint"), str) else None,
                }
            )

    if not entry_candidates:
        for context in (loc0.get("context", []), loc1.get("context", [])):
            if context:
                top = context[0]
                if isinstance(top, str):
                    top_entries.append(top)
                    entry_candidates.append(
                        {
                            "confidence": "heuristic",
                            "entry_func": top,
                            "entry_kind_hint": None,
                        }
                    )

    deduped_top_entries = list(dict.fromkeys(top_entries))
    deduped_entry_candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in entry_candidates:
        entry_func = candidate["entry_func"]
        if entry_func in seen:
            continue
        seen.add(entry_func)
        deduped_entry_candidates.append(candidate)

    return {"entry_candidates": deduped_entry_candidates, "top_entries": deduped_top_entries}


def _site_list(raw_items: Any, include_object_hint: bool = True) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        record = {
            "function": item.get("function") if isinstance(item.get("function"), str) else "unknown",
            "stmt": item.get("stmt") if isinstance(item.get("stmt"), str) else None,
        }
        if include_object_hint:
            record["object_hint"] = item.get("object_hint") if isinstance(item.get("object_hint"), str) else None
        normalized.append(record)
    return normalized


def export_bridge_candidate(raw_warning: dict[str, Any]) -> dict[str, Any]:
    loc0 = _normalize_location(raw_warning.get("free_site"))
    loc1 = _normalize_location(raw_warning.get("use_site"))
    efp = raw_warning.get("efp") if isinstance(raw_warning.get("efp"), dict) else {}

    return {
        "condition_summary": {
            "conditions": raw_warning.get("condition_ops", []) if isinstance(raw_warning.get("condition_ops"), list) else []
        },
        "constraint_summary": {
            "partial_order": raw_warning.get("partial_order", []) if isinstance(raw_warning.get("partial_order"), list) else [],
            "predicates": raw_warning.get("predicate_hints", []) if isinstance(raw_warning.get("predicate_hints"), list) else [],
            "same_object": raw_warning.get("object_hints", {}).get("same_object") if isinstance(raw_warning.get("object_hints"), dict) else None,
        },
        "efp_summary": {
            "clobber_sites": _site_list(efp.get("clobber_sites", []), include_object_hint=False),
            "escape_sites": _site_list(efp.get("escape_sites", []), include_object_hint=True),
            "fetch_sites": _site_list(efp.get("fetch_sites", []), include_object_hint=True),
        },
        "entry_summary": _entry_summary(raw_warning, loc0, loc1),
        "export_version": EXPORT_VERSION,
        "flow": raw_warning.get("flow") if isinstance(raw_warning.get("flow"), str) else "Unknown",
        "kernel_area": raw_warning.get("kernel_area") if isinstance(raw_warning.get("kernel_area"), str) else "arch/arm64/kvm",
        "loc0": loc0,
        "loc1": loc1,
        "lock_summary": {
            "locks": raw_warning.get("lock_ops", []) if isinstance(raw_warning.get("lock_ops"), list) else []
        },
        "raw_warning": raw_warning,
        "source_tool": "uafx",
        "thread_summary": {
            "events": raw_warning.get("thread_ops", []) if isinstance(raw_warning.get("thread_ops"), list) else []
        },
        "warning_id": raw_warning.get("warning_id") if isinstance(raw_warning.get("warning_id"), str) else "unknown-warning-id",
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export one raw UAFX warning into bridge JSON")
    parser.add_argument("--input", required=True, help="Path to raw UAFX warning JSON")
    parser.add_argument("--output", required=True, help="Path to output richer bridge export JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    raw_warning = load_json(Path(args.input))
    payload = export_bridge_candidate(raw_warning)
    write_json(Path(args.output), payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
