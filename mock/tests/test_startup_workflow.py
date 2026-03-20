from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


MOCK_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = MOCK_ROOT / "scripts"
CHECK_SCRIPT = SCRIPTS_DIR / "check_kvm_fuzz_prereqs.sh"
RUN_SCRIPT = SCRIPTS_DIR / "run_kvm_seed_fuzz.sh"
COMPAT_RUN_SCRIPT = SCRIPTS_DIR / "run_kvm_seeded_fuzz.sh"
PREPARE_SCRIPT = SCRIPTS_DIR / "prepare_kvm_seed.sh"
COMPARE_SCRIPT = SCRIPTS_DIR / "run_seeded_vs_unseeded_compare.sh"


def _write_text(path: Path, content: str = "stub") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _make_seed_workdir(root: Path) -> Path:
    seed_workdir = root / "seed_workdir"
    _write_text(seed_workdir / "input" / "seed_00.prog", "openat$KVM(0)\n")
    _write_text(seed_workdir / "relations" / "bridge_seed.relations", "openat$KVM,ioctl$KVM_CREATE_VM\n")
    _write_text(seed_workdir / "bias.json", json.dumps({"candidate_id": "cand_demo"}) + "\n")
    return seed_workdir


def _make_syz_dir(root: Path, *, direct_layout: bool) -> Path:
    syz_dir = root / ("syz-bin-direct" if direct_layout else "syz-root")
    if direct_layout:
        base = syz_dir
    else:
        base = syz_dir / "bin"
    _write_text(base / "linux_arm64" / "syz-executor")
    _write_text(base / "syz-repro")
    _write_text(base / "syz-symbolize")
    return syz_dir


def _make_runtime_assets(root: Path) -> dict[str, Path]:
    assets = {
        "disk": _write_text(root / "disk.img"),
        "ssh_key": _write_text(root / "stretch.id_rsa"),
        "kernel": _write_text(root / "Image"),
    }
    assets["seed_workdir"] = _make_seed_workdir(root)
    return assets


class StartupWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="startup-workflow-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _base_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["BRIDGE_ROOT"] = str(self.tmpdir / "bridge-root")
        (self.tmpdir / "bridge-root" / "out").mkdir(parents=True, exist_ok=True)
        return env

    def _check_cmd(
        self,
        assets: dict[str, Path],
        syz_dir: Path,
    ) -> list[str]:
        return [
            "bash",
            str(CHECK_SCRIPT),
            "--seed-workdir",
            str(assets["seed_workdir"]),
            "--syz-dir",
            str(syz_dir),
            str(assets["disk"]),
            str(assets["ssh_key"]),
            str(assets["kernel"]),
        ]

    def test_shell_scripts_have_valid_syntax(self) -> None:
        for script in (
            PREPARE_SCRIPT,
            CHECK_SCRIPT,
            RUN_SCRIPT,
            COMPAT_RUN_SCRIPT,
            COMPARE_SCRIPT,
        ):
            with self.subTest(script=script.name):
                proc = subprocess.run(["bash", "-n", str(script)], cwd=MOCK_ROOT, capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_prereq_checker_accepts_both_syz_layouts(self) -> None:
        for direct_layout in (False, True):
            with self.subTest(direct_layout=direct_layout):
                case_dir = self.tmpdir / ("direct" if direct_layout else "root")
                assets = _make_runtime_assets(case_dir)
                syz_dir = _make_syz_dir(case_dir, direct_layout=direct_layout)
                proc = subprocess.run(
                    self._check_cmd(assets, syz_dir),
                    cwd=MOCK_ROOT,
                    capture_output=True,
                    text=True,
                    env=self._base_env(),
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn("Startup prerequisites look good.", proc.stdout)
                self.assertIn("model manager", proc.stdout)

    def test_prereq_checker_reports_actionable_failures(self) -> None:
        cases = (
            ("disk image not found", lambda assets, syz_dir: assets["disk"].unlink()),
            ("ssh key not found", lambda assets, syz_dir: assets["ssh_key"].unlink()),
            ("kernel image not found", lambda assets, syz_dir: assets["kernel"].unlink()),
            ("seed input directory not found", lambda assets, syz_dir: shutil.rmtree(assets["seed_workdir"] / "input")),
            ("seed relations file not found", lambda assets, syz_dir: (assets["seed_workdir"] / "relations" / "bridge_seed.relations").unlink()),
            ("bridge bias file not found", lambda assets, syz_dir: (assets["seed_workdir"] / "bias.json").unlink()),
            (
                "missing syz-executor",
                lambda assets, syz_dir: next(syz_dir.rglob("syz-executor")).unlink(),
            ),
        )

        for expected_message, mutate in cases:
            with self.subTest(expected_message=expected_message):
                case_dir = self.tmpdir / expected_message.replace(" ", "-")
                assets = _make_runtime_assets(case_dir)
                syz_dir = _make_syz_dir(case_dir, direct_layout=False)
                mutate(assets, syz_dir)
                proc = subprocess.run(
                    self._check_cmd(assets, syz_dir),
                    cwd=MOCK_ROOT,
                    capture_output=True,
                    text=True,
                    env=self._base_env(),
                )
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn(expected_message, proc.stderr + proc.stdout)

    def test_run_script_dry_run_uses_checker_and_writes_summary(self) -> None:
        assets = _make_runtime_assets(self.tmpdir / "run-script")
        syz_dir = _make_syz_dir(self.tmpdir / "run-script", direct_layout=True)
        output_dir = self.tmpdir / "output"
        fake_bin = self.tmpdir / "fake-bin"
        fake_bin.mkdir(parents=True, exist_ok=True)
        cargo_args_log = self.tmpdir / "cargo-args.json"
        fake_cargo = fake_bin / "cargo"
        fake_cargo.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import json",
                    "import os",
                    "import pathlib",
                    "import sys",
                    "pathlib.Path(os.environ['CARGO_ARGS_LOG']).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')",
                    "args = sys.argv[1:]",
                    "if '--debug-summary-json' in args:",
                    "    idx = args.index('--debug-summary-json') + 1",
                    "    out = pathlib.Path(args[idx])",
                    "    out.parent.mkdir(parents=True, exist_ok=True)",
                    "    out.write_text('{\"ok\": true}\\n', encoding='utf-8')",
                    "print('fake cargo invoked')",
                ]
            ),
            encoding="utf-8",
        )
        fake_cargo.chmod(0o755)

        env = self._base_env()
        env["PATH"] = f"{fake_bin}:{env['PATH']}"
        env["CARGO_ARGS_LOG"] = str(cargo_args_log)

        proc = subprocess.run(
            [
                "bash",
                str(RUN_SCRIPT),
                "--dry-run",
                "--seed-workdir",
                str(assets["seed_workdir"]),
                "--output-dir",
                str(output_dir),
                "--syz-dir",
                str(syz_dir),
                str(assets["disk"]),
                str(assets["ssh_key"]),
                str(assets["kernel"]),
            ],
            cwd=MOCK_ROOT,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((output_dir / "debug-summary.json").is_file())
        self.assertIn("Dry-run summary written to:", proc.stdout)

        cargo_args = json.loads(cargo_args_log.read_text(encoding="utf-8"))
        self.assertIn("--dry-run", cargo_args)
        self.assertIn("--debug-summary-json", cargo_args)
        self.assertIn("--bridge-bias", cargo_args)
        self.assertIn("-i", cargo_args)
        self.assertIn("-R", cargo_args)
        self.assertIn("-S", cargo_args)

    def test_compat_run_script_shim_execs_canonical_script(self) -> None:
        assets = _make_runtime_assets(self.tmpdir / "compat-run")
        syz_dir = _make_syz_dir(self.tmpdir / "compat-run", direct_layout=True)
        output_dir = self.tmpdir / "compat-output"
        fake_bin = self.tmpdir / "compat-fake-bin"
        fake_bin.mkdir(parents=True, exist_ok=True)
        cargo_args_log = self.tmpdir / "compat-cargo-args.json"
        fake_cargo = fake_bin / "cargo"
        fake_cargo.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import json",
                    "import os",
                    "import pathlib",
                    "import sys",
                    "pathlib.Path(os.environ['CARGO_ARGS_LOG']).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')",
                    "args = sys.argv[1:]",
                    "if '--debug-summary-json' in args:",
                    "    idx = args.index('--debug-summary-json') + 1",
                    "    out = pathlib.Path(args[idx])",
                    "    out.parent.mkdir(parents=True, exist_ok=True)",
                    "    out.write_text('{\"ok\": true}\\n', encoding='utf-8')",
                ]
            ),
            encoding="utf-8",
        )
        fake_cargo.chmod(0o755)

        env = self._base_env()
        env["PATH"] = f"{fake_bin}:{env['PATH']}"
        env["CARGO_ARGS_LOG"] = str(cargo_args_log)

        proc = subprocess.run(
            [
                "bash",
                str(COMPAT_RUN_SCRIPT),
                "--dry-run",
                "--seed-workdir",
                str(assets["seed_workdir"]),
                "--output-dir",
                str(output_dir),
                "--syz-dir",
                str(syz_dir),
                str(assets["disk"]),
                str(assets["ssh_key"]),
                str(assets["kernel"]),
            ],
            cwd=MOCK_ROOT,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((output_dir / "debug-summary.json").is_file())


if __name__ == "__main__":
    unittest.main()
