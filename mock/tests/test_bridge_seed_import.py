from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from bridge_seed.importer import import_bridge_seed, load_bridge_seed
from bridge_seed.policy import build_mutation_bias


MOCK_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_ROOT = MOCK_ROOT.parent / "uaf-bridge"
SEED_PATH = BRIDGE_ROOT / "out" / "uafx_kvm_mock_seed.json"


class BridgeSeedImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not SEED_PATH.exists():
            script = BRIDGE_ROOT / "scripts" / "run_end_to_end_kvm_demo.sh"
            env = dict(os.environ)
            subprocess.run(["bash", str(script)], check=True, cwd=BRIDGE_ROOT, env=env)

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="mock-seed-test-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_seed_loads_cleanly(self) -> None:
        seed = load_bridge_seed(SEED_PATH)
        self.assertEqual(seed["arch"], "arm64")
        self.assertEqual(seed["subsystem"], "kvm")

    def test_importer_generates_corpus_and_bias(self) -> None:
        preview = import_bridge_seed(SEED_PATH, self.tmpdir)
        self.assertGreaterEqual(preview["program_count"], 2)
        input_dir = self.tmpdir / "input"
        relations_path = self.tmpdir / "relations" / "bridge_seed.relations"
        bias_path = self.tmpdir / "bias.json"
        self.assertTrue(input_dir.is_dir())
        self.assertTrue(relations_path.is_file())
        self.assertTrue(bias_path.is_file())
        first_prog = next(iter(sorted(input_dir.iterdir())))
        content = first_prog.read_text(encoding="utf-8")
        self.assertIn("openat$KVM", content)
        self.assertIn("KVM_CREATE_VM", content)

    def test_bias_has_kvm_focus_and_concurrency(self) -> None:
        seed = load_bridge_seed(SEED_PATH)
        bias = build_mutation_bias(seed)
        self.assertIn("KVM_RUN", bias["focus_syscall_families"])
        self.assertTrue(bias["prefer_two_thread_schedule"])
        self.assertTrue(bias["prefer_collide"])
        self.assertEqual(bias["preserve_prefix_len"], 3)
        self.assertEqual(bias["preserve_prefix_len"], len(seed["setup_sequence"]))
        self.assertIn("escape->fetch", bias["keep_ordering_edges"])

    def test_import_is_deterministic(self) -> None:
        out_a = self.tmpdir / "a"
        out_b = self.tmpdir / "b"
        import_bridge_seed(SEED_PATH, out_a)
        import_bridge_seed(SEED_PATH, out_b)
        self.assertEqual(
            json.loads((out_a / "bias.json").read_text(encoding="utf-8")),
            json.loads((out_b / "bias.json").read_text(encoding="utf-8")),
        )
        progs_a = sorted(path.read_text(encoding="utf-8") for path in sorted((out_a / "input").iterdir()))
        progs_b = sorted(path.read_text(encoding="utf-8") for path in sorted((out_b / "input").iterdir()))
        self.assertEqual(progs_a, progs_b)

    def test_import_overwrites_stale_generated_files(self) -> None:
        out_dir = self.tmpdir / "overwrite"
        import_bridge_seed(SEED_PATH, out_dir)

        stale_input = out_dir / "input" / "stale.prog"
        stale_preview = out_dir / "preview" / "stale.txt"
        stale_relation = out_dir / "relations" / "stale.relations"
        stale_input.write_text("stale", encoding="utf-8")
        stale_preview.write_text("stale", encoding="utf-8")
        stale_relation.write_text("stale", encoding="utf-8")

        import_bridge_seed(SEED_PATH, out_dir)

        self.assertFalse(stale_input.exists())
        self.assertFalse(stale_preview.exists())
        self.assertFalse(stale_relation.exists())
        self.assertTrue((out_dir / "input" / "seed_00.prog").is_file())
        self.assertTrue((out_dir / "preview" / "summary.json").is_file())
        self.assertTrue((out_dir / "relations" / "bridge_seed.relations").is_file())

    def test_prepare_script_generates_expected_artifacts(self) -> None:
        workdir = self.tmpdir / "seeded"
        script = MOCK_ROOT / "scripts" / "prepare_kvm_seed.sh"
        env = dict(os.environ)
        env["BRIDGE_ROOT"] = str(BRIDGE_ROOT)
        subprocess.run(["bash", str(script), str(workdir)], check=True, cwd=MOCK_ROOT, env=env)
        self.assertTrue((workdir / "input").is_dir())
        self.assertTrue((workdir / "relations" / "bridge_seed.relations").is_file())
        self.assertTrue((workdir / "bias.json").is_file())


if __name__ == "__main__":
    unittest.main()
