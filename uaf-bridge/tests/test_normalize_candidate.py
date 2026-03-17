"""Tests for candidate normalization."""

from __future__ import annotations

import json
from pathlib import Path

from extractor.normalize_candidate import normalize_warning


SAMPLE_PATH = Path(__file__).resolve().parents[1] / "extractor" / "sample_warn_data.json"


def test_normalize_candidate_required_fields() -> None:
    raw_warning = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    candidate = normalize_warning(raw_warning, raw_file=str(SAMPLE_PATH))

    assert isinstance(candidate["candidate_id"], str)
    assert candidate["schema_version"] == "candidate/v1"
    assert candidate["raw_warning"] == raw_warning
    assert candidate["flow"] == "Con"
    assert candidate["status"]["supported"] is True
    assert candidate["status"]["ready_for_smt"] is True
    assert candidate["status"]["grounded_entries"] == ["demo_uaf_ioctl", "demo_uaf_read"]
    assert candidate["status"]["heuristic_entries"] == []
    assert candidate["status"]["unsupported_entries"] == []

    assert isinstance(candidate["entries"], list)
    assert len(candidate["entries"]) >= 1
    assert any(entry["syscall_templates"] for entry in candidate["entries"])

    ioctl_entry = next(entry for entry in candidate["entries"] if entry["entry_func"] == "demo_uaf_ioctl")
    assert ioctl_entry["grounded"]["mapping_source"] == "manual"
    assert ioctl_entry["heuristic"] == {}
    assert ioctl_entry["supported"] is True


def test_normalize_candidate_marks_unsupported_entries_explicitly() -> None:
    raw_warning = {
        "loc0": {"context": ["mystery_trigger"]},
        "loc1": {"context": ["totally_unknown_entry"]},
        "flow": "Seq",
    }

    candidate = normalize_warning(raw_warning, raw_file="dummy.json")

    assert [entry["entry_kind"] for entry in candidate["entries"]] == ["unknown", "unknown"]
    assert all(entry["supported"] is False for entry in candidate["entries"])
    assert candidate["status"]["supported"] is False
    assert candidate["status"]["ready_for_smt"] is False
    assert candidate["status"]["unsupported_entries"] == ["mystery_trigger", "totally_unknown_entry"]
