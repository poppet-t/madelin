from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
CHECK_ENV_PATH = ROOT / "scripts" / "check_env.py"


def _load_check_env_module():
    spec = importlib.util.spec_from_file_location("uaf_bridge_check_env", CHECK_ENV_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check_env = _load_check_env_module()


class CheckEnvTests(unittest.TestCase):
    def test_run_checks_reports_error_and_skipped_dependents(self) -> None:
        checks = [
            check_env.CheckSpec(name="json", detail="json importable", import_name="json"),
            check_env.CheckSpec(
                name="missing_pkg",
                detail="missing module importable",
                import_name="definitely_missing_bridge_pkg",
            ),
            check_env.CheckSpec(
                name="dependent",
                detail="dependent module importable",
                import_name="json",
                depends_on=("missing_pkg",),
            ),
        ]

        results = check_env.run_checks(checks)
        by_name = {result.name: result for result in results}

        self.assertEqual(by_name["json"].status, "ok")
        self.assertEqual(by_name["missing_pkg"].status, "error")
        self.assertEqual(by_name["dependent"].status, "skip")
        self.assertTrue(check_env.has_required_failures(results))

    def test_optional_failure_does_not_count_as_required_failure(self) -> None:
        checks = [
            check_env.CheckSpec(
                name="optional_missing",
                detail="optional module importable",
                import_name="definitely_missing_bridge_pkg",
                required=False,
            ),
        ]

        results = check_env.run_checks(checks)

        self.assertEqual(results[0].status, "error")
        self.assertFalse(check_env.has_required_failures(results))


if __name__ == "__main__":
    unittest.main()
