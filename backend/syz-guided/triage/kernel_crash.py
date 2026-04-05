from __future__ import annotations

import hashlib
import re
from typing import Any

from triage.parse_kasan import _extract_source_files, _extract_stack_frames, parse_kasan_report

_REAL_CRASH_KINDS = {"kasan", "oops", "bug"}


def parse_kernel_crash(text: str) -> dict[str, Any] | None:
    if not text.strip():
        return None

    kasan = parse_kasan_report(text)
    if kasan is not None:
        title = _first_matching_line(text, [r"BUG:\s+KASAN:", r"Read of size", r"Write of size"])
        return _finalize(
            kind="kasan",
            title=title or f"BUG: KASAN: {kasan.get('type', 'unknown')} in {kasan.get('trigger_function', 'unknown')}",
            bug_type=kasan.get("type", "unknown"),
            text=text,
            parsed=kasan,
        )

    patterns: list[tuple[str, list[str], str]] = [
        ("bug", [r"kernel BUG at", r"BUG:\s+unable to handle", r"BUG:"], "kernel BUG"),
        ("oops", [r"Oops:", r"Internal error:"], "kernel OOPS"),
        ("warning", [r"WARNING:"], "kernel WARNING"),
        ("hang", [r"hung task", r"soft lockup", r"watchdog: BUG:", r"rcu: INFO:"], "kernel hang"),
    ]
    for kind, regexes, fallback in patterns:
        title = _first_matching_line(text, regexes)
        if title:
            parsed = {
                "type": fallback,
                "trigger_function": _extract_stack_frames(text)[0] if _extract_stack_frames(text) else "unknown",
                "allocator": None,
                "stack_frames": _extract_stack_frames(text),
                "source_files": _extract_source_files(text),
            }
            return _finalize(kind=kind, title=title, bug_type=fallback, text=text, parsed=parsed)

    return None


def is_real_crash_signal(crash: dict[str, Any] | None) -> bool:
    return bool(crash and crash.get("kind") in _REAL_CRASH_KINDS)


def build_crash_signature(crash: dict[str, Any] | None) -> str | None:
    if not crash:
        return None
    signature_parts = [crash.get("kind", "unknown"), crash.get("title", "unknown")]
    signature_parts.extend(crash.get("top_frames", [])[:3])
    material = "|".join(signature_parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _first_matching_line(text: str, patterns: list[str]) -> str | None:
    for line in text.splitlines():
        for pattern in patterns:
            if re.search(pattern, line, re.IGNORECASE):
                return line.strip()
    return None


def _finalize(
    *,
    kind: str,
    title: str,
    bug_type: str,
    text: str,
    parsed: dict[str, Any],
) -> dict[str, Any]:
    frames = parsed.get("stack_frames", [])
    return {
        "kind": kind,
        "bug_type": bug_type,
        "title": title,
        "trigger_function": parsed.get("trigger_function", "unknown"),
        "allocator": parsed.get("allocator"),
        "stack_frames": frames,
        "top_frames": frames[:5],
        "source_files": parsed.get("source_files", []),
        "raw_excerpt": text[:4000],
        "signature": build_crash_signature(
            {
                "kind": kind,
                "title": title,
                "top_frames": frames[:5],
            }
        ),
        "is_real_crash_signal": kind in _REAL_CRASH_KINDS,
    }
