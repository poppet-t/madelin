from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from verdict.aggregate import aggregate_verdict


MATCHING_UAF_LOG = """BUG: KASAN: use-after-free in kvm_timer_should_fire+0x20/0x70 arch/arm64/kvm/arch_timer.c:923
Read of size 8 at addr 0xffff000012340000 by task syz-executor/1234

Call trace:
 kvm_timer_should_fire+0x20/0x70 arch/arm64/kvm/arch_timer.c:923
 kvm_vcpu_ioctl+0x120/0x2b0 arch/arm64/kvm/arm.c:342

Freed by task 1234:
 kvm_timer_vcpu_terminate+0x94/0x1b0 arch/arm64/kvm/arch_timer.c:812
"""


def _candidate_payload() -> dict:
    return {
        "candidate_id": "cand_demo",
        "analysis_context": {"kernel_area": "arch/arm64/kvm"},
        "loc0": {"function": "kvm_timer_vcpu_terminate", "file": "arch/arm64/kvm/arch_timer.c", "line": 812},
        "loc1": {"function": "kvm_timer_should_fire", "file": "arch/arm64/kvm/arch_timer.c", "line": 923},
        "entries": [{"entry_func": "kvm_vcpu_ioctl"}],
    }


class VerdictAggregateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="verdict-aggregate-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_run_result(
        self,
        *,
        timing_us: int,
        run_index: int,
        setup_failed: bool = False,
        candidate_reached: bool = True,
        timing_window_entered: bool = True,
        execution_completed: bool = True,
        crash_log_text: str | None = None,
    ) -> None:
        run_dir = self.tmpdir / "output" / "runs" / f"{timing_us}us" / f"run-{run_index}"
        run_dir.mkdir(parents=True, exist_ok=True)
        crash_log_path = None
        if crash_log_text is not None:
            crash_log_path = run_dir / "dmesg-delta.log"
            crash_log_path.write_text(crash_log_text, encoding="utf-8")
        payload = {
            "timing_us": timing_us,
            "run_index": run_index,
            "exit_code": 0 if not setup_failed else 2,
            "setup_failed": setup_failed,
            "candidate_reached": candidate_reached,
            "timing_window_entered": timing_window_entered,
            "execution_completed": execution_completed,
            "stdout_log": str(run_dir / "stdout.log"),
            "stderr_log": str(run_dir / "stderr.log"),
            "dmesg_before_log": str(run_dir / "dmesg-before.log"),
            "dmesg_after_log": str(run_dir / "dmesg-after.log"),
            "dmesg_delta_log": str(run_dir / "dmesg-delta.log"),
            "crash_log": str(crash_log_path) if crash_log_path is not None else None,
        }
        (run_dir / "result.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")

    def test_aggregate_verdict_prefers_confirmed_timing(self) -> None:
        candidate_path = self.tmpdir / "candidate.json"
        candidate_path.write_text(json.dumps(_candidate_payload()), encoding="utf-8")
        self._write_run_result(timing_us=0, run_index=1, crash_log_text=None)
        self._write_run_result(timing_us=1000, run_index=1, crash_log_text=MATCHING_UAF_LOG)
        self._write_run_result(timing_us=1000, run_index=2, crash_log_text=None)

        verdict = aggregate_verdict(
            output_dir=self.tmpdir / "output",
            candidate_path=candidate_path,
            execution_metadata={"execution_mode": "harness_timing_sweep", "wall_seconds": 7},
        )

        self.assertEqual(verdict["verdict"], "CONFIRMED")
        self.assertEqual(verdict["execution"]["best_timing_us"], 1000)
        self.assertEqual(verdict["execution"]["crashes_matched"], 1)
        self.assertEqual(verdict["execution"]["runs_total"], 3)

    def test_aggregate_verdict_reports_timing_inconclusive_without_crashes(self) -> None:
        candidate_path = self.tmpdir / "candidate.json"
        candidate_path.write_text(json.dumps(_candidate_payload()), encoding="utf-8")
        self._write_run_result(timing_us=0, run_index=1, crash_log_text=None)
        self._write_run_result(timing_us=100, run_index=1, crash_log_text=None)

        verdict = aggregate_verdict(
            output_dir=self.tmpdir / "output",
            candidate_path=candidate_path,
            execution_metadata={"execution_mode": "harness_timing_sweep", "wall_seconds": 3},
        )

        self.assertEqual(verdict["verdict"], "TIMING_INCONCLUSIVE")
        self.assertEqual(verdict["confidence"], "medium")


if __name__ == "__main__":
    unittest.main()
