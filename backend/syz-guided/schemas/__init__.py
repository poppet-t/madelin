"""Schema loading and validation for syz-guided backend artifacts."""

import json
import pathlib

_SCHEMA_DIR = pathlib.Path(__file__).parent

SCHEMA_NAMES = [
    "state_model_v1",
    "target_profile",
    "relation_graph_v1",
    "triage_report_v1",
]


def load_schema(name: str) -> dict:
    """Load a JSON schema by short name (e.g. 'state_model_v1')."""
    path = _SCHEMA_DIR / f"{name}.schema.json"
    if not path.exists():
        raise FileNotFoundError(f"Schema not found: {path}")
    with open(path) as f:
        return json.load(f)


def validate(instance: dict, schema_name: str) -> list[str]:
    """Validate a dict against a named schema. Returns list of error messages (empty = valid)."""
    try:
        import jsonschema
    except ImportError:
        # Fallback: basic required-field check only
        return _basic_validate(instance, schema_name)

    schema = load_schema(schema_name)
    validator = jsonschema.Draft202012Validator(schema)
    return [e.message for e in validator.iter_errors(instance)]


def _basic_validate(instance: dict, schema_name: str) -> list[str]:
    """Minimal validation without jsonschema: check required top-level fields."""
    schema = load_schema(schema_name)
    required = schema.get("required", [])
    missing = [f for f in required if f not in instance]
    errors = []
    if missing:
        errors.append(f"Missing required fields: {missing}")
    version_prop = schema.get("properties", {}).get("schema_version", {})
    expected = version_prop.get("const")
    if expected and instance.get("schema_version") != expected:
        errors.append(
            f"schema_version must be '{expected}', got '{instance.get('schema_version')}'"
        )
    return errors
