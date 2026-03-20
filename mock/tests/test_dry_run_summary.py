from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

MOCK_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_ROOT = MOCK_ROOT.parent / "uaf-bridge"
SEED_SCRIPT = MOCK_ROOT / "scripts" / "prepare_kvm_seed.sh"


@unittest.skipUnless(os.environ.get("RUN_CARGO_DRY_RUN_TEST") == "1", "set RUN_CARGO_DRY_RUN_TEST=1 to enable cargo-based dry-run test")
class DryRunSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="dry-run-"))
        self.seed_workdir = self.tmpdir / "seed_workdir"
        env = dict(os.environ)
        env["BRIDGE_ROOT"] = str(BRIDGE_ROOT)
        subprocess.run(["bash", str(SEED_SCRIPT), str(self.seed_workdir)], check=True, cwd=MOCK_ROOT, env=env)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_seeded_dry_run_reports_expected_fields(self) -> None:
        output_dir = self.tmpdir / "output"
        summary_path = output_dir / "debug-summary.json"
        syz_dir = self.tmpdir / "syz-bin"
        cmd = [
            "cargo",
            "run",
            "--release",
            "-p",
            "healer_fuzzer",
            "--bin",
            "healer",
            "--",
            "--arch",
            "arm64",
            "--bridge-bias",
            str(self.seed_workdir / "bias.json"),
            "-d",
            str(self.tmpdir / "dummy.img"),
            "--ssh-key",
            str(self.tmpdir / "dummy.key"),
            "-k",
            str(self.tmpdir / "dummy-kernel"),
            "-S",
            str(syz_dir),
            "-i",
            str(self.seed_workdir / "input"),
            "-R",
            str(self.seed_workdir / "relations" / "bridge_seed.relations"),
            "-o",
            str(output_dir),
            "--dry-run",
            "--debug-summary-json",
            str(summary_path),
        ]
        # create minimal placeholders so config validation can inspect the paths before dry-run returns
        (self.tmpdir / "dummy.img").write_text("img", encoding="utf-8")
        (self.tmpdir / "dummy.key").write_text("key", encoding="utf-8")
        (self.tmpdir / "dummy-kernel").write_text("kernel", encoding="utf-8")
        (syz_dir / "linux_arm64").mkdir(parents=True, exist_ok=True)
        (syz_dir / "linux_arm64" / "syz-executor").write_text("stub", encoding="utf-8")
        (syz_dir / "syz-repro").write_text("stub", encoding="utf-8")
        (syz_dir / "syz-symbolize").write_text("stub", encoding="utf-8")
        proc = subprocess.run(cmd, cwd=MOCK_ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("target: linux/arm64", proc.stdout)
        self.assertIn("bridge_bias_loaded: true", proc.stdout)
        self.assertIn("input_seed_program_count:", proc.stdout)
        self.assertIn("relation_edge_count:", proc.stdout)
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["target"], "linux/arm64")
        self.assertTrue(payload["bridge_bias_loaded"])
        self.assertGreater(payload["input_seed_program_count"], 0)
        self.assertGreater(payload["relation_edge_count"], 0)
        self.assertGreater(len(payload["focus_syscall_families"]), 0)


if __name__ == "__main__":
    unittest.main()
