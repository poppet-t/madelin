#!/usr/bin/env python3
"""Bridge environment preflight for the narrow KVM verifier workflow."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_INSTALL_HINT = "python3 -m pip install -e .[dev]"


@dataclass(frozen=True)
class CheckSpec:
    name: str
    detail: str
    import_name: str | None = None
    required: bool = True
    install_hint: str | None = DEFAULT_INSTALL_HINT
    depends_on: tuple[str, ...] = ()
    min_python: tuple[int, int] | None = None


@dataclass(frozen=True)
class CheckResult:
    name: str
    detail: str
    status: str
    message: str
    required: bool
    install_hint: str | None = None


def build_default_checks() -> list[CheckSpec]:
    return [
        CheckSpec(
            name="python",
            detail="Python >= 3.11",
            min_python=(3, 11),
            install_hint="Use Python 3.11 or newer for uaf-bridge",
        ),
        CheckSpec(
            name="jsonschema",
            detail="jsonschema importable",
            import_name="jsonschema",
        ),
        CheckSpec(
            name="z3",
            detail="z3 / z3-solver importable",
            import_name="z3",
        ),
        CheckSpec(
            name="extractor.import_uafx_bridge_export",
            detail="bridge candidate importer importable",
            import_name="extractor.import_uafx_bridge_export",
            depends_on=("jsonschema",),
        ),
        CheckSpec(
            name="common.schema_validation",
            detail="schema validation module importable",
            import_name="common.schema_validation",
            depends_on=("jsonschema",),
        ),
        CheckSpec(
            name="smt.solve_candidate",
            detail="solver entrypoint importable",
            import_name="smt.solve_candidate",
            depends_on=("jsonschema", "z3"),
        ),
        CheckSpec(
            name="runtime.emit_witness_syz",
            detail="witness emitter importable",
            import_name="runtime.emit_witness_syz",
            depends_on=("jsonschema",),
        ),
        CheckSpec(
            name="runtime.validate_witness",
            detail="witness validator importable",
            import_name="runtime.validate_witness",
            depends_on=("jsonschema",),
        ),
        CheckSpec(
            name="runtime.export_mock_seed",
            detail="mock seed exporter importable",
            import_name="runtime.export_mock_seed",
            depends_on=("jsonschema",),
        ),
        CheckSpec(
            name="harness.generate_harness",
            detail="harness generator importable",
            import_name="harness.generate_harness",
            depends_on=("jsonschema",),
        ),
        CheckSpec(
            name="pytest",
            detail="pytest importable for bridge tests",
            import_name="pytest",
            required=False,
        ),
    ]


def run_checks(checks: list[CheckSpec]) -> list[CheckResult]:
    status_by_name: dict[str, bool] = {}
    results: list[CheckResult] = []

    for check in checks:
        missing_dependencies = [name for name in check.depends_on if not status_by_name.get(name, False)]
        if missing_dependencies:
            results.append(
                CheckResult(
                    name=check.name,
                    detail=check.detail,
                    status="skip",
                    message=f"waiting on prerequisite checks: {', '.join(missing_dependencies)}",
                    required=check.required,
                    install_hint=check.install_hint,
                )
            )
            status_by_name[check.name] = False
            continue

        if check.min_python is not None:
            actual = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
            wanted = f"{check.min_python[0]}.{check.min_python[1]}"
            ok = sys.version_info >= check.min_python
            results.append(
                CheckResult(
                    name=check.name,
                    detail=check.detail,
                    status="ok" if ok else "error",
                    message=f"found {actual}" if ok else f"found {actual}, expected >= {wanted}",
                    required=check.required,
                    install_hint=check.install_hint,
                )
            )
            status_by_name[check.name] = ok
            continue

        if check.import_name is None:
            raise ValueError(f"check {check.name} has no import_name or min_python")

        try:
            importlib.import_module(check.import_name)
        except Exception as exc:
            results.append(
                CheckResult(
                    name=check.name,
                    detail=check.detail,
                    status="error",
                    message=f"{exc.__class__.__name__}: {exc}",
                    required=check.required,
                    install_hint=check.install_hint,
                )
            )
            status_by_name[check.name] = False
        else:
            results.append(
                CheckResult(
                    name=check.name,
                    detail=check.detail,
                    status="ok",
                    message="ready",
                    required=check.required,
                    install_hint=check.install_hint,
                )
            )
            status_by_name[check.name] = True

    return results


def has_required_failures(results: list[CheckResult]) -> bool:
    return any(result.required and result.status == "error" for result in results)


def print_results(results: list[CheckResult]) -> None:
    for result in results:
        print(f"[check_env] {result.status:5} {result.name}: {result.detail} ({result.message})")
        if result.status == "error" and result.install_hint:
            print(f"[check_env] hint  {result.name}: {result.install_hint}")

    if has_required_failures(results):
        print("[check_env] bridge environment is not ready", file=sys.stderr)
    else:
        print("[check_env] bridge environment looks ready")


def main() -> int:
    results = run_checks(build_default_checks())
    print_results(results)
    return 1 if has_required_failures(results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
