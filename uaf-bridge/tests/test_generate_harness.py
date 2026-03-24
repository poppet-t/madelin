from __future__ import annotations

import json
import unittest
from pathlib import Path

from extractor.import_uafx_bridge_export import import_uafx_bridge_export
from harness.generate_harness import render_harness
from smt.solve_candidate import solve_candidate


ROOT = Path(__file__).resolve().parents[1]
EXPORT_PATH = ROOT / "extractor" / "sample_uafx_kvm_bridge_export.json"


def _sample_candidate_and_plan() -> tuple[dict[str, object], dict[str, object]]:
    export_payload = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    candidate = import_uafx_bridge_export(export_payload, raw_file=str(EXPORT_PATH))
    plan = solve_candidate(candidate)
    return candidate, plan


class GenerateHarnessTests(unittest.TestCase):
    def test_generate_harness_renders_narrow_kvm_timer_program(self) -> None:
        candidate, plan = _sample_candidate_and_plan()

        harness = render_harness(candidate, plan)

        self.assertIn(candidate["candidate_id"], harness)
        self.assertIn("harness_family: kvm_arm64_timer_close_vs_run", harness)
        self.assertIn("kvm_timer_vcpu_terminate", harness)
        self.assertIn("kvm_timer_should_fire", harness)
        self.assertIn("ioctl(fd, KVM_RUN, 0)", harness)
        self.assertIn("close(fd)", harness)
        self.assertIn("pthread_barrier_wait", harness)
        self.assertIn("HARNESS: timing_window_entered=%d", harness)

    def test_generate_harness_rejects_unsupported_candidate_shape(self) -> None:
        candidate, plan = _sample_candidate_and_plan()
        candidate["loc1"]["function"] = "unsupported_use_site"

        with self.assertRaisesRegex(ValueError, "unsupported harness candidate family: .*close-vs-run family"):
            render_harness(candidate, plan)


if __name__ == "__main__":
    unittest.main()
