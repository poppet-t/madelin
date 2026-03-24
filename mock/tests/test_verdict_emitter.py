from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from verdict.emit_verdict import emit_verdict, resolve_candidate_path


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


class VerdictEmitterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="verdict-emitter-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_emit_verdict_writes_confirmed_result(self) -> None:
        output_dir = self.tmpdir / "output"
        crash_dir = output_dir / "crashes" / "uaf-demo"
        crash_dir.mkdir(parents=True, exist_ok=True)
        (crash_dir / "log1").write_text(MATCHING_UAF_LOG, encoding="utf-8")

        candidate_path = self.tmpdir / "candidate.json"
        candidate_path.write_text(json.dumps(_candidate_payload()), encoding="utf-8")

        verdict = emit_verdict(
            output_dir=output_dir,
            candidate_path=candidate_path,
            execution_metadata={"seeded_run_completed": True, "wall_seconds": 12},
        )

        self.assertEqual(verdict["verdict"], "CONFIRMED")
        self.assertEqual(verdict["execution"]["crashes_total"], 1)
        self.assertEqual(verdict["execution"]["crashes_matched"], 1)
        self.assertTrue((output_dir / "verdict.json").is_file())

    def test_emit_verdict_without_crashes_reports_reached_no_crash(self) -> None:
        output_dir = self.tmpdir / "output-no-crash"
        output_dir.mkdir(parents=True, exist_ok=True)
        candidate_path = self.tmpdir / "candidate.json"
        candidate_path.write_text(json.dumps(_candidate_payload()), encoding="utf-8")

        verdict = emit_verdict(
            output_dir=output_dir,
            candidate_path=candidate_path,
            execution_metadata={"seeded_run_completed": True, "wall_seconds": 4},
        )

        self.assertEqual(verdict["verdict"], "REACHED_NO_CRASH")
        self.assertEqual(verdict["execution"]["crashes_total"], 0)

    def test_emit_verdict_without_crashes_accepts_generic_execution_completion(self) -> None:
        output_dir = self.tmpdir / "output-witness-no-crash"
        output_dir.mkdir(parents=True, exist_ok=True)
        candidate_path = self.tmpdir / "candidate.json"
        candidate_path.write_text(json.dumps(_candidate_payload()), encoding="utf-8")

        verdict = emit_verdict(
            output_dir=output_dir,
            candidate_path=candidate_path,
            execution_metadata={
                "execution_completed": True,
                "witness_run_completed": True,
                "execution_mode": "witness_remote",
                "wall_seconds": 3,
            },
        )

        self.assertEqual(verdict["verdict"], "REACHED_NO_CRASH")
        self.assertEqual(verdict["execution"]["execution_mode"], "witness_remote")

    def test_resolve_candidate_falls_back_to_imported_seed(self) -> None:
        seed_workdir = self.tmpdir / "seed_workdir"
        seed_workdir.mkdir(parents=True, exist_ok=True)
        (seed_workdir / "bias.json").write_text(json.dumps({"candidate_id": "cand_demo"}), encoding="utf-8")
        imported_seed = {
            "candidate_id": "cand_demo",
            "debug": {
                "loc0": {"function": "demo_free", "file": "arch/arm64/kvm/demo.c", "line": 10},
                "loc1": {"function": "demo_use", "file": "arch/arm64/kvm/demo.c", "line": 20},
            },
            "entries": [{"entry_func": "demo_ioctl"}],
        }
        (seed_workdir / "imported_seed.json").write_text(json.dumps(imported_seed), encoding="utf-8")

        resolved = resolve_candidate_path(seed_workdir=seed_workdir, bridge_root=self.tmpdir / "missing-bridge")

        self.assertEqual(resolved, seed_workdir / "imported_seed.json")


if __name__ == "__main__":
    unittest.main()
