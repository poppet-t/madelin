from __future__ import annotations

from pathlib import Path
import re
from typing import Any


FRAME_RE = re.compile(
    r"^\s*(?:\[<[^>]+>\]\s*)?(?P<function>[A-Za-z0-9_.$]+)"
    r"(?:\+0x[0-9a-fA-F]+/0x[0-9a-fA-F]+)?"
    r"(?:\s+(?P<file>[^:\s]+):(?P<line>\d+))?"
)

FAULT_PATTERNS = (
    re.compile(r"\bat addr (?P<addr>0x[0-9a-fA-F]+)\b"),
    re.compile(r"\baddress (?P<addr>0x[0-9a-fA-F]+)\b"),
    re.compile(r"\bbuggy address .* (?P<addr>0x[0-9a-fA-F]+)\b"),
)

CRASH_TYPE_PATTERNS = (
    ("use-after-free", re.compile(r"\buse-after-free\b", re.IGNORECASE)),
    ("slab-out-of-bounds", re.compile(r"\bslab-out-of-bounds\b", re.IGNORECASE)),
    ("null-deref", re.compile(r"(null pointer dereference|NULL pointer dereference)", re.IGNORECASE)),
)

ACCESS_RE = re.compile(r"\b(Read|Write) of size\b", re.IGNORECASE)
SECTION_MARKERS = {
    "free_stack": ("freed by task",),
    "alloc_stack": ("allocated by task",),
    "stack_frames": ("call trace:", "call trace"),
}


def _detect_crash_type(raw: str) -> str | None:
    for crash_type, pattern in CRASH_TYPE_PATTERNS:
        if pattern.search(raw):
            return crash_type
    return None


def _detect_access(raw: str) -> str | None:
    match = ACCESS_RE.search(raw)
    if match is None:
        return None
    return match.group(1).lower()


def _detect_faulting_address(raw: str) -> str | None:
    for pattern in FAULT_PATTERNS:
        match = pattern.search(raw)
        if match is not None:
            return match.group("addr")
    return None


def _parse_frame(line: str) -> dict[str, Any] | None:
    stripped = line.lstrip()
    lowered = stripped.lower()
    if lowered.startswith(("bug:", "read of size", "write of size", "unable to handle")):
        return None

    match = FRAME_RE.match(line)
    if match is None:
        return None

    function = match.group("function")
    if function in {"Call", "Freed", "Allocated", "BUG"}:
        return None

    frame: dict[str, Any] = {"function": function}
    file_name = match.group("file")
    if file_name:
        frame["file"] = file_name
    line_number = match.group("line")
    if line_number:
        frame["line"] = int(line_number)
    return frame


def parse_crash_text(raw: str) -> dict[str, Any]:
    section = "stack_frames"
    stack_frames: list[dict[str, Any]] = []
    free_stack: list[dict[str, Any]] = []
    alloc_stack: list[dict[str, Any]] = []

    for line in raw.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        for next_section, markers in SECTION_MARKERS.items():
            if any(lowered.startswith(marker) for marker in markers):
                section = next_section
                break

        frame = _parse_frame(line)
        if frame is None:
            continue

        if section == "free_stack":
            free_stack.append(frame)
        elif section == "alloc_stack":
            alloc_stack.append(frame)
        else:
            stack_frames.append(frame)

    return {
        "crash_type": _detect_crash_type(raw),
        "access": _detect_access(raw),
        "faulting_address": _detect_faulting_address(raw),
        "stack_frames": stack_frames,
        "free_stack": free_stack,
        "alloc_stack": alloc_stack,
        "raw": raw,
    }


def parse_crash_file(path: str | Path) -> dict[str, Any]:
    return parse_crash_text(Path(path).read_text(encoding="utf-8", errors="replace"))
