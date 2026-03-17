"""Helpers for extracting thread schedules from SMT models."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def sort_events_by_timestamp(event_timestamps: Mapping[str, int]) -> list[dict[str, Any]]:
    """Return events sorted by timestamp then event name with stable indices."""
    ordered = sorted(event_timestamps.items(), key=lambda item: (item[1], item[0]))
    return [
        {"event": event, "step_index": index, "timestamp": timestamp}
        for index, (event, timestamp) in enumerate(ordered)
    ]


def group_steps_by_thread(
    ordered_steps: Sequence[Mapping[str, Any]],
    event_threads: Mapping[str, int],
) -> list[dict[str, Any]]:
    """Group ordered steps by thread assignment."""
    by_thread: dict[int, list[dict[str, Any]]] = {}

    for step in ordered_steps:
        event = str(step["event"])
        thread_id = int(event_threads[event])
        by_thread.setdefault(thread_id, []).append(
            {
                "event": event,
                "step_index": int(step["step_index"]),
                "timestamp": int(step["timestamp"]),
            }
        )

    threads: list[dict[str, Any]] = []
    for thread_id in sorted(by_thread.keys()):
        steps = sorted(by_thread[thread_id], key=lambda s: (s["step_index"], s["timestamp"], s["event"]))
        threads.append({"steps": steps, "thread_id": thread_id})

    return threads


def build_barriers(partial_order: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Convert partial-order constraints into runtime barrier edge objects."""
    barriers: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for edge in partial_order:
        before = edge.get("before")
        after = edge.get("after")
        reason = edge.get("reason")
        if not (isinstance(before, str) and isinstance(after, str) and isinstance(reason, str)):
            continue

        key = (before, after, reason)
        if key in seen:
            continue
        seen.add(key)

        barriers.append({"after": after, "before": before, "reason": reason})

    return sorted(barriers, key=lambda edge: (edge["before"], edge["after"], edge["reason"]))
