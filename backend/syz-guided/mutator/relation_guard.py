"""Relation guard — validates that a mutated program preserves resource flow.

This module checks whether a program's call list still satisfies the
producer→consumer constraints from the relation graph.  Used as a
post-mutation filter.
"""

from __future__ import annotations


def check_resource_chain(calls: list[str], state_model: dict) -> list[str]:
    """Check that all resource chain constraints are satisfied.

    Returns a list of violation descriptions (empty = valid).
    """
    violations = []
    call_positions: dict[str, int] = {}
    for i, c in enumerate(calls):
        if c not in call_positions:
            call_positions[c] = i

    for res in state_model.get("resource_chain", []):
        producer = res["producer_call"]
        if producer not in call_positions:
            violations.append(f"Missing producer '{producer}' for resource '{res['resource']}'")
            continue

        prod_pos = call_positions[producer]
        for consumer in res.get("consumer_calls", []):
            if consumer in call_positions and call_positions[consumer] <= prod_pos:
                violations.append(
                    f"Consumer '{consumer}' at position {call_positions[consumer]} "
                    f"appears before producer '{producer}' at position {prod_pos} "
                    f"for resource '{res['resource']}'"
                )

    return violations


def check_prefix_intact(calls: list[str], state_model: dict) -> bool:
    """Check that the immutable prefix is intact."""
    prefix_len = state_model.get("immutable_prefix_len", 0)
    bootstrap = state_model["phases"]["bootstrap"]["calls"]
    if len(calls) < prefix_len:
        return False
    return all(calls[i] == bootstrap[i] for i in range(prefix_len))


def is_valid_mutation(calls: list[str], state_model: dict) -> tuple[bool, list[str]]:
    """Full validation of a mutated program. Returns (valid, violations)."""
    violations = []
    if not check_prefix_intact(calls, state_model):
        violations.append("Immutable prefix was modified")
    violations.extend(check_resource_chain(calls, state_model))
    return len(violations) == 0, violations
