from __future__ import annotations

import json
from pathlib import Path

from extractor.import_uafx_bridge_export import import_uafx_bridge_export
from mock_adapter.import_seed import import_seed
from mock_adapter.seed_to_mock_program import render_mock_program
from runtime.export_mock_seed import export_mock_seed
from smt.solve_candidate import solve_candidate


EXPORT_PATH = Path(__file__).resolve().parents[1] / "extractor" / "sample_uafx_kvm_bridge_export.json"


def test_mock_seed_roundtrip_is_deterministic_and_non_empty() -> None:
    export_payload = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    candidate = import_uafx_bridge_export(export_payload, raw_file=str(EXPORT_PATH))
    plan = solve_candidate(candidate)
    seed_a = export_mock_seed(candidate, plan)
    seed_b = export_mock_seed(candidate, plan)

    assert seed_a == seed_b

    imported = import_seed(seed_a)
    text = render_mock_program(seed_a)

    assert imported["candidate_id"] == seed_a["candidate_id"]
    assert imported["mutation_policy"]["preserve_prefix_len"] == seed_a["mutation_hints"]["preserve_prefix_len"]
    assert imported["corpus_program"]["threads"] == seed_a["threads"]
    assert imported["corpus_program"]["setup_calls"]
    assert imported["corpus_program"]["trigger_calls"]
    assert text.strip() != ""
    assert "[setup_sequence]" in text
    assert "[mutation_policy]" in text
    assert "KVM_CREATE_VM" in text
    assert "KVM_RUN" in text
