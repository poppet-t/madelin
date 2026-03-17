"""Encode normalized candidates into Z3 constraints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from z3 import ArithRef, Distinct, Int, Optimize


@dataclass
class EncodedProblem:
    """Container for an encoded SMT problem and its symbols."""

    optimizer: Optimize
    time_vars: dict[str, ArithRef]
    thread_vars: dict[str, ArithRef]
    events: list[str]
    partial_order: list[dict[str, str]]
    min_threads: int
    flow: str
    soft_constraints: list[str]


def _normalize_events(candidate: dict[str, Any]) -> list[str]:
    constraints = candidate.get("constraints", {})
    raw_events = constraints.get("events", []) if isinstance(constraints, dict) else []
    if not isinstance(raw_events, list):
        raise ValueError("constraints.events must be an array of strings")

    events = [event for event in raw_events if isinstance(event, str)]
    if not events:
        raise ValueError("constraints.events cannot be empty")

    return list(dict.fromkeys(events))


def _normalize_partial_order(candidate: dict[str, Any]) -> list[dict[str, str]]:
    constraints = candidate.get("constraints", {})
    raw_edges = constraints.get("partial_order", []) if isinstance(constraints, dict) else []
    if not isinstance(raw_edges, list):
        raise ValueError("constraints.partial_order must be an array")

    edges: list[dict[str, str]] = []
    for edge in raw_edges:
        if not isinstance(edge, dict):
            continue
        before = edge.get("before")
        after = edge.get("after")
        reason = edge.get("reason")
        if isinstance(before, str) and isinstance(after, str) and isinstance(reason, str):
            edges.append({"before": before, "after": after, "reason": reason})
    return edges


def _min_threads(candidate: dict[str, Any]) -> int:
    constraints = candidate.get("constraints", {})
    value = constraints.get("min_threads") if isinstance(constraints, dict) else None
    if isinstance(value, int) and value >= 1:
        return value
    raise ValueError("constraints.min_threads must be an integer >= 1")


def encode_candidate(candidate: dict[str, Any]) -> EncodedProblem:
    """Encode a normalized candidate into an SMT optimization problem."""
    events = _normalize_events(candidate)
    partial_order = _normalize_partial_order(candidate)
    min_threads = _min_threads(candidate)
    flow = str(candidate.get("flow", "Unknown"))

    optimizer = Optimize()
    time_vars: dict[str, ArithRef] = {}
    thread_vars: dict[str, ArithRef] = {}

    for event in events:
        time_var = Int(f"t_{event}")
        thread_var = Int(f"th_{event}")

        time_vars[event] = time_var
        thread_vars[event] = thread_var

        optimizer.add(time_var >= 0)
        optimizer.add(thread_var >= 0)
        optimizer.add(thread_var < min_threads)

    if len(events) > 1:
        optimizer.add(Distinct(*[time_vars[event] for event in events]))

    for edge in partial_order:
        before = edge["before"]
        after = edge["after"]
        if before in time_vars and after in time_vars:
            optimizer.add(time_vars[before] < time_vars[after])

    soft_constraints: list[str] = []
    if flow == "Con" and min_threads >= 2 and "free" in thread_vars and "use" in thread_vars:
        optimizer.add_soft(thread_vars["free"] != thread_vars["use"], weight="1", id="prefer_split_threads")
        soft_constraints.append("prefer_split_threads: free/use on different threads when feasible")

    return EncodedProblem(
        optimizer=optimizer,
        time_vars=time_vars,
        thread_vars=thread_vars,
        events=events,
        partial_order=partial_order,
        min_threads=min_threads,
        flow=flow,
        soft_constraints=soft_constraints,
    )
