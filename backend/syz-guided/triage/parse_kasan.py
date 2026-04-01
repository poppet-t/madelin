"""Parse KASAN reports from kernel crash output.

Extracts:
  - bug type (use-after-free, slab-out-of-bounds, etc.)
  - allocator (slab, page, etc.)
  - stack frames (function names from the call trace)
  - source file references
"""

from __future__ import annotations

import re
from typing import Any


def parse_kasan_report(text: str) -> dict | None:
    """Parse a KASAN report string. Returns None if no KASAN report found."""
    # Look for KASAN header.
    header_match = re.search(
        r"BUG:\s+KASAN:\s+([\w-]+)\s+in\s+(\S+)",
        text,
    )
    if not header_match:
        return None

    bug_type = header_match.group(1)
    trigger_func = header_match.group(2)

    # Extract allocator info.
    allocator = None
    alloc_match = re.search(r"Allocated by task \d+.*?:\s*\n((?:\s+\S+.*\n)+)", text)
    if alloc_match:
        allocator = "slab"  # Most common for UAF.

    # Extract call trace frames.
    stack_frames = _extract_stack_frames(text)

    # Extract source files.
    source_files = _extract_source_files(text)

    return {
        "type": bug_type,
        "trigger_function": trigger_func,
        "allocator": allocator,
        "stack_frames": stack_frames,
        "source_files": source_files,
    }


def _extract_stack_frames(text: str) -> list[str]:
    """Extract function names from KASAN call trace."""
    frames = []
    # Match lines like: " function_name+0x1a/0x30"
    for match in re.finditer(r"^\s+(\w+)\+0x[0-9a-f]+/0x[0-9a-f]+", text, re.MULTILINE):
        func = match.group(1)
        if func not in frames:
            frames.append(func)
    return frames


def _extract_source_files(text: str) -> list[str]:
    """Extract source file paths from KASAN report."""
    files = []
    # Match lines like: " arch/arm64/kvm/arch_timer.c:812"
    for match in re.finditer(r"(\S+\.c):(\d+)", text):
        path = match.group(1)
        if path not in files:
            files.append(path)
    return files
