from __future__ import annotations

import pytest

from common.schema_validation import SchemaValidationError, validate_candidate, validate_mock_seed, validate_witness_plan


def test_validate_candidate_rejects_missing_schema_version() -> None:
    with pytest.raises(SchemaValidationError):
        validate_candidate({"candidate_id": "cand_demo"})


def test_validate_witness_plan_rejects_missing_status() -> None:
    with pytest.raises(SchemaValidationError):
        validate_witness_plan({"candidate_id": "cand_demo", "schema_version": "witness_plan/v1", "sat": True})


def test_validate_mock_seed_rejects_missing_required_fields() -> None:
    with pytest.raises(SchemaValidationError):
        validate_mock_seed({"candidate_id": "cand_demo", "seed_version": "mock_seed/v1"})
