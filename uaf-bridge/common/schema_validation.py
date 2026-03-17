from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "jsonschema is required for runtime schema validation; install project dependencies"
    ) from exc


SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"


class SchemaValidationError(ValueError):
    """Raised when a JSON payload fails schema validation."""


@lru_cache(maxsize=None)
def load_schema(schema_name: str) -> dict[str, Any]:
    path = SCHEMA_DIR / schema_name
    if not path.exists():
        raise FileNotFoundError(f"Schema file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _format_path(parts: list[Any]) -> str:
    if not parts:
        return "$"
    rendered: list[str] = ["$"]
    for part in parts:
        if isinstance(part, int):
            rendered.append(f"[{part}]")
        else:
            rendered.append(f".{part}")
    return "".join(rendered)


def validate_against_schema(payload: dict[str, Any], schema_name: str, candidate_id: str | None = None) -> None:
    """Validate a payload against one of the repo JSON schemas."""
    schema = load_schema(schema_name)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.absolute_path))
    if not errors:
        return

    first = errors[0]
    path_text = _format_path(list(first.absolute_path))
    cid = candidate_id or payload.get("candidate_id")
    prefix = f"candidate_id={cid}: " if isinstance(cid, str) else ""
    raise SchemaValidationError(f"{prefix}{schema_name} validation failed at {path_text}: {first.message}")


def validate_candidate(payload: dict[str, Any]) -> None:
    validate_against_schema(payload, "candidate.schema.json")


def validate_witness_plan(payload: dict[str, Any]) -> None:
    validate_against_schema(payload, "witness_plan.schema.json")


def validate_mock_seed(payload: dict[str, Any]) -> None:
    validate_against_schema(payload, "mock_seed.schema.json")
