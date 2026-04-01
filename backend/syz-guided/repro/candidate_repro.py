"""Candidate-preserving repro wrapper.

Wraps syzkaller's repro/minimization to ensure:
  1. The immutable bootstrap prefix is never minimized away.
  2. Sticky calls (configure phase) are preserved by default.
  3. Resource chain integrity is maintained.

In v1 this is a policy wrapper, not a syzkaller patch.
The wrapper filters the minimized program through relation_guard
and rejects minimizations that break the prefix.
"""

from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from mutator.relation_guard import is_valid_mutation


def validate_repro(
    repro_calls: list[str],
    original_calls: list[str],
    state_model: dict,
) -> dict:
    """Validate a reproduced/minimized program preserves candidate constraints.

    Returns:
        dict with 'valid' (bool), 'violations' (list), and 'recommendation'
    """
    valid, violations = is_valid_mutation(repro_calls, state_model)

    # Check that the repro doesn't minimize away too much.
    original_trigger = [c for c in original_calls if c in state_model.get("favored_suffix_calls", [])]
    repro_trigger = [c for c in repro_calls if c in state_model.get("favored_suffix_calls", [])]

    if original_trigger and not repro_trigger:
        violations.append(
            "Repro minimized away all favored suffix calls — "
            "may have lost the trigger for the candidate's free/use region"
        )
        valid = False

    recommendation = "accept" if valid else "reject_restore_prefix"

    return {
        "valid": valid,
        "violations": violations,
        "recommendation": recommendation,
        "original_call_count": len(original_calls),
        "repro_call_count": len(repro_calls),
    }
