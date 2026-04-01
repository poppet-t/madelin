"""Prefix-safe mutation policy for candidate-directed fuzzing.

Mutation rules (v1):
  1. Bootstrap prefix is immutable — never mutate calls[0:immutable_prefix_len].
  2. Sticky calls (bootstrap + configure) must not be removed.
  3. Suffix calls may be reordered, duplicated, or replaced.
  4. Producer→consumer resource flow must be preserved.
  5. Exploration budget is narrow — prefer small perturbations.
"""

from __future__ import annotations

import random
from typing import Any


def mutate(
    calls: list[str],
    state_model: dict,
    rng: random.Random | None = None,
) -> list[str]:
    """Apply prefix-safe mutation to a program's call list.

    Returns a new call list (does not modify the input).
    """
    rng = rng or random.Random()
    prefix_len = state_model.get("immutable_prefix_len", 0)
    sticky = set(state_model.get("sticky_calls", []))
    favored = state_model.get("favored_suffix_calls", [])

    # Immutable prefix + sticky configure region.
    prefix = list(calls[:prefix_len])
    sticky_region = [c for c in calls[prefix_len:] if c in sticky]
    suffix = [c for c in calls[prefix_len:] if c not in sticky]

    # Pick a mutation strategy.
    strategies = [
        _append_favored,
        _duplicate_suffix,
        _shuffle_suffix,
        _drop_non_sticky_suffix,
    ]
    strategy = rng.choice(strategies)
    mutated_suffix = strategy(suffix, favored, rng)

    return prefix + sticky_region + mutated_suffix


def _append_favored(suffix: list[str], favored: list[str], rng: random.Random) -> list[str]:
    """Append a favored suffix call."""
    if not favored:
        return list(suffix)
    return list(suffix) + [rng.choice(favored)]


def _duplicate_suffix(suffix: list[str], favored: list[str], rng: random.Random) -> list[str]:
    """Duplicate a random suffix call."""
    if not suffix:
        return list(suffix)
    result = list(suffix)
    idx = rng.randrange(len(result))
    result.insert(idx + 1, result[idx])
    return result


def _shuffle_suffix(suffix: list[str], favored: list[str], rng: random.Random) -> list[str]:
    """Shuffle non-sticky suffix calls."""
    result = list(suffix)
    rng.shuffle(result)
    return result


def _drop_non_sticky_suffix(suffix: list[str], favored: list[str], rng: random.Random) -> list[str]:
    """Drop one non-sticky suffix call (if more than one exists)."""
    if len(suffix) <= 1:
        return list(suffix)
    result = list(suffix)
    idx = rng.randrange(len(result))
    result.pop(idx)
    return result
