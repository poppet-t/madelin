"""Helpers for extracting thread schedules from SMT models."""

from __future__ import annotations

import heapq
from typing import Any, Mapping, Sequence

_EVENT_PRIORITY = {
    "free": 0,
    "use": 1,
    "escape": 2,
    "fetch": 3,
    "cleanup": 4,
    "init_resource": 5,
}


def _event_sort_key(event: str) -> tuple[int, str]:
    return (_EVENT_PRIORITY.get(event, len(_EVENT_PRIORITY)), event)


def sort_events_by_timestamp(event_timestamps: Mapping[str, int]) -> list[dict[str, Any]]:
    """Return events sorted by timestamp then event name with stable indices."""
    ordered = sorted(event_timestamps.items(), key=lambda item: (item[1], item[0]))
    return [
        {"event": event, "step_index": index, "timestamp": timestamp}
        for index, (event, timestamp) in enumerate(ordered)
    ]


def canonical_ordered_steps(
    events: Sequence[str],
    partial_order: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build a deterministic topological order for plan events."""
    event_list = [str(event) for event in events]
    indegree = {event: 0 for event in event_list}
    outgoing = {event: set() for event in event_list}

    for edge in partial_order:
        before = edge.get("before")
        after = edge.get("after")
        if not (isinstance(before, str) and isinstance(after, str)):
            continue
        if before not in indegree or after not in indegree:
            continue
        if after in outgoing[before]:
            continue
        outgoing[before].add(after)
        indegree[after] += 1

    ready = [_event_sort_key(event) + (event,) for event, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    ordered: list[str] = []

    while ready:
        _, _, event = heapq.heappop(ready)
        ordered.append(event)
        for successor in sorted(outgoing[event], key=_event_sort_key):
            indegree[successor] -= 1
            if indegree[successor] == 0:
                heapq.heappush(ready, _event_sort_key(successor) + (successor,))

    if len(ordered) != len(event_list):
        ordered = sorted(event_list, key=_event_sort_key)

    return [
        {"event": event, "step_index": index, "timestamp": index}
        for index, event in enumerate(ordered)
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


def canonical_thread_map(
    events: Sequence[str],
    flow: str,
    min_threads: int,
) -> dict[str, int]:
    """Build a deterministic thread assignment for the witness plan."""
    event_list = [str(event) for event in events]
    thread_map = {event: 0 for event in event_list}
    if flow == "Con" and min_threads >= 2 and "use" in thread_map:
        thread_map["use"] = 1
    return thread_map
