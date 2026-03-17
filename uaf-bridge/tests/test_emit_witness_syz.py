"""Tests for witness scaffold emission."""

from __future__ import annotations

import json
from pathlib import Path

from extractor.normalize_candidate import normalize_warning
from runtime.emit_witness_syz import render_witness
from smt.solve_candidate import solve_candidate


SAMPLE_PATH = Path(__file__).resolve().parents[1] / "extractor" / "sample_warn_data.json"


def test_emit_witness_syz_non_empty_output() -> None:
    raw_warning = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    candidate = normalize_warning(raw_warning, raw_file=str(SAMPLE_PATH))
    plan = solve_candidate(candidate)
    witness = render_witness(candidate, plan)

    assert witness.strip() != ""
    assert candidate["candidate_id"] in witness
    assert "thread_" in witness
    assert "step_index=" in witness
    assert "not a fully runnable syzkaller program" in witness
