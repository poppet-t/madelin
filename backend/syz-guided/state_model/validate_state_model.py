#!/usr/bin/env python3
"""Validate a state_model_v1.json against the schema."""

from __future__ import annotations

import json
import pathlib
import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: validate_state_model.py <state_model_v1.json>", file=sys.stderr)
        return 1

    path = pathlib.Path(sys.argv[1])
    with open(path) as f:
        data = json.load(f)

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from schemas import validate

    errors = validate(data, "state_model_v1")
    if errors:
        print(f"FAIL: {len(errors)} error(s) in {path}:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    print(f"OK: {path} validates against state_model_v1 schema")
    return 0


if __name__ == "__main__":
    sys.exit(main())
