"""Tests for SMT candidate solving."""

from __future__ import annotations

import json
from pathlib import Path

from extractor.normalize_candidate import normalize_warning
from smt.solve_candidate import solve_candidate


SAMPLE_PATH = Path(__file__).resolve().parents[1] / "extractor" / "sample_warn_data.json"


def test_solve_candidate_sat_for_sample_warning() -> None:
    raw_warning = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    candidate = normalize_warning(raw_warning, raw_file=str(SAMPLE_PATH))
    plan = solve_candidate(candidate)

    assert plan["sat"] is True
    assert plan["status"] == "sat"
    assert plan["schema_version"] == "witness_plan/v1"
    assert plan["candidate_id"] == candidate["candidate_id"]
    assert isinstance(plan["threads"], list)
    assert len(plan["threads"]) >= 1
    assert isinstance(plan["ordered_steps"], list)
    assert len(plan["ordered_steps"]) == len(candidate["constraints"]["events"])

    barrier_pairs = {(edge["before"], edge["after"]) for edge in plan["barriers"]}
    assert ("escape", "fetch") in barrier_pairs
    assert ("free", "use") in barrier_pairs

    assert plan["ordered_steps"][0]["step_index"] == 0
    assert sorted(step["step_index"] for step in plan["ordered_steps"]) == list(
        range(len(plan["ordered_steps"]))
    )
