"""Entry classification utilities for v1 UAF witness bridging."""

from __future__ import annotations

from typing import List


ENTRY_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("ioctl", "file_ioctl"),
    ("read", "file_read"),
    ("write", "file_write"),
    ("show", "sysfs_show"),
    ("store", "sysfs_store"),
)


def classify_entry(entry_func: str) -> str:
    """Classify a candidate entry function into a v1 entry kind."""
    lowered = entry_func.lower()
    for needle, entry_kind in ENTRY_KEYWORDS:
        if needle in lowered:
            return entry_kind
    return "unknown"


def infer_entry_functions(loc0_context: List[str], loc1_context: List[str]) -> List[str]:
    """Infer likely entry function names from location contexts with stable dedupe.

    v1 stays intentionally narrow: use the first frame from each context as the likely entry.
    Unsupported entries are preserved explicitly instead of being silently dropped.
    """
    ordered: list[str] = []
    seen: set[str] = set()

    for context in (loc0_context, loc1_context):
        if not context:
            continue
        symbol = context[0]
        if not isinstance(symbol, str):
            continue
        cleaned = symbol.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)

    return ordered
