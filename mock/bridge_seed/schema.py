from __future__ import annotations

from typing import Any


REQUIRED_TOP_LEVEL = {
    "seed_version",
    "candidate_id",
    "target",
    "arch",
    "subsystem",
    "flow",
    "threads",
    "setup_sequence",
    "trigger_sequence",
    "ordering",
    "mutation_hints",
}


class SeedValidationError(ValueError):
    pass


def validate_seed(payload: dict[str, Any]) -> None:
    missing = sorted(REQUIRED_TOP_LEVEL.difference(payload))
    if missing:
        raise SeedValidationError(f"mock_seed missing required fields: {', '.join(missing)}")
    if payload.get("target") != "linux":
        raise SeedValidationError("mock_seed.target must be 'linux'")
    if payload.get("subsystem") != "kvm":
        raise SeedValidationError("mock_seed.subsystem must be 'kvm' for this importer")
    if payload.get("arch") != "arm64":
        raise SeedValidationError("mock_seed.arch must be 'arm64' for KVM arm64 workflow")
    if not isinstance(payload.get("threads"), int) or payload["threads"] < 1:
        raise SeedValidationError("mock_seed.threads must be an integer >= 1")
    for field in ("setup_sequence", "trigger_sequence", "ordering"):
        if not isinstance(payload.get(field), list):
            raise SeedValidationError(f"mock_seed.{field} must be a list")
    if not isinstance(payload.get("mutation_hints"), dict):
        raise SeedValidationError("mock_seed.mutation_hints must be an object")
