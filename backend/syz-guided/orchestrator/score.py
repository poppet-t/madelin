"""Multi-dimensional scoring for candidate-directed fuzzing programs.

Score dimensions:
  prefix_valid   — bootstrap prefix is intact
  resource_chain — producer→consumer fd chain is preserved
  phase_progress — how far into bootstrap→configure→trigger the program gets
  target_signal  — coverage or crash signals near candidate focus frames/files
  order_preserved — witness ordering constraints are respected
"""

from __future__ import annotations

from typing import Any


def score_program(
    program_calls: list[str],
    state_model: dict,
    target_profile: dict,
    signals: dict | None = None,
) -> dict:
    """Score a program against the state model and target profile.

    Args:
        program_calls: ordered list of canonical call names in the program
        state_model: state_model_v1.json contents
        target_profile: target_profile.json contents
        signals: optional dict with keys like 'covered_frames', 'crash_frames',
                 'covered_files' from the latest execution

    Returns:
        dict with individual dimension scores (0.0–1.0) and weighted total
    """
    signals = signals or {}
    weights = state_model.get("score_weights", {})

    dims = {
        "prefix_valid": _score_prefix(program_calls, state_model),
        "resource_chain": _score_resource_chain(program_calls, state_model),
        "phase_progress": _score_phase_progress(program_calls, state_model),
        "target_signal": _score_target_signal(signals, target_profile),
        "order_preserved": _score_order(program_calls, state_model),
    }

    total = sum(dims[k] * weights.get(k, 0.0) for k in dims)

    return {**dims, "total": total}


def _score_prefix(calls: list[str], sm: dict) -> float:
    """1.0 if immutable prefix is intact, 0.0 otherwise."""
    prefix_len = sm.get("immutable_prefix_len", 0)
    bootstrap = sm["phases"]["bootstrap"]["calls"]
    if len(calls) < prefix_len:
        return 0.0
    for i in range(prefix_len):
        if i >= len(bootstrap) or calls[i] != bootstrap[i]:
            return 0.0
    return 1.0


def _score_resource_chain(calls: list[str], sm: dict) -> float:
    """Fraction of resource chain entries whose producer appears before consumers."""
    chain = sm.get("resource_chain", [])
    if not chain:
        return 1.0

    call_set = set(calls)
    score_parts = 0
    total_parts = 0

    for res in chain:
        producer = res["producer_call"]
        consumers = res.get("consumer_calls", [])
        if producer not in call_set:
            total_parts += 1
            continue
        prod_idx = calls.index(producer)
        for consumer in consumers:
            total_parts += 1
            if consumer in call_set:
                con_idx = calls.index(consumer)
                if con_idx > prod_idx:
                    score_parts += 1

    return score_parts / total_parts if total_parts > 0 else 1.0


def _score_phase_progress(calls: list[str], sm: dict) -> float:
    """0.0 if no bootstrap calls, 0.33 if bootstrap done, 0.66 if configure done, 1.0 if trigger reached."""
    phases = sm["phases"]
    call_set = set(calls)

    bootstrap_done = all(c in call_set for c in phases["bootstrap"]["calls"])
    configure_done = all(c in call_set for c in phases["configure"]["calls"])
    trigger_done = any(c in call_set for c in phases["trigger"]["calls"])

    if trigger_done and configure_done and bootstrap_done:
        return 1.0
    if configure_done and bootstrap_done:
        return 0.66
    if bootstrap_done:
        return 0.33
    return 0.0


def _score_target_signal(signals: dict, tp: dict) -> float:
    """Score based on how close execution signals are to candidate targets."""
    if not signals:
        return 0.0

    focus_frames = set(tp.get("focus_frames", []))
    focus_files = set(tp.get("focus_files", []))

    covered_frames = set(signals.get("covered_frames", []))
    covered_files = set(signals.get("covered_files", []))
    crash_frames = set(signals.get("crash_frames", []))

    # Frame hits are most valuable.
    frame_hits = len(focus_frames & (covered_frames | crash_frames))
    file_hits = len(focus_files & covered_files)

    frame_score = min(frame_hits / max(len(focus_frames), 1), 1.0)
    file_score = min(file_hits / max(len(focus_files), 1), 1.0)

    # Crash frame hits are a strong signal.
    crash_bonus = 0.5 if (focus_frames & crash_frames) else 0.0

    return min(0.5 * frame_score + 0.3 * file_score + crash_bonus, 1.0)


def _score_order(calls: list[str], sm: dict) -> float:
    """Fraction of precedence edges that are satisfied by call ordering."""
    edges = sm.get("precedence_edges", [])
    if not edges:
        return 1.0

    # Map event names to approximate call positions (best-effort for v1).
    # This is a structural check — events map loosely to phases.
    # In v1 we just check that the prefix is intact (order is implicit).
    return 1.0 if _score_prefix(calls, sm) == 1.0 else 0.5
