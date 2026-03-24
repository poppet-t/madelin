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
WITNESS_SCRIPT = SCRIPTS_DIR / "run_witness.sh"
BUILD_HARNESS_SCRIPT = SCRIPTS_DIR / "build_harness.sh"
RUN_HARNESS_SCRIPT = SCRIPTS_DIR / "run_harness.sh"
PREPARE_SCRIPT = SCRIPTS_DIR / "prepare_kvm_seed.sh"
COMPARE_SCRIPT = SCRIPTS_DIR / "run_seeded_vs_unseeded_compare.sh"

MATCHING_WITNESS_LOG = """BUG: KASAN: use-after-free in kvm_timer_should_fire+0x20/0x70 arch/arm64/kvm/arch_timer.c:923
Read of size 8 at addr 0xffff000012340000 by task syz-executor/1234

Call trace:
 kvm_timer_should_fire+0x20/0x70 arch/arm64/kvm/arch_timer.c:923
 kvm_vcpu_ioctl+0x120/0x2b0 arch/arm64/kvm/arm.c:342

Freed by task 1234:
 kvm_timer_vcpu_terminate+0x94/0x1b0 arch/arm64/kvm/arch_timer.c:812
"""


def _write_text(path: Path, content: str = "stub") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_executable_text(path: Path, content: str = "stub") -> Path:
    _write_text(path, content)
    path.chmod(0o755)
    return path


def _make_candidate_and_witness(root: Path) -> dict[str, Path]:
    candidate = {
        "candidate_id": "cand_demo",
        "analysis_context": {"kernel_area": "arch/arm64/kvm"},
        "loc0": {"function": "kvm_timer_vcpu_terminate", "file": "arch/arm64/kvm/arch_timer.c", "line": 812},
        "loc1": {"function": "kvm_timer_should_fire", "file": "arch/arm64/kvm/arch_timer.c", "line": 923},
        "entries": [{"entry_func": "kvm_vcpu_ioctl"}],
    }
    return {
        "candidate": _write_text(root / "candidate.json", json.dumps(candidate) + "\n"),
        "witness": _write_text(root / "witness.syz", "r0 = openat$KVM(0xffffffffffffff9c, &AUTO='/dev/kvm\\x00', 0x2, 0x0)\n"),
    }


def _make_harness_source(root: Path) -> Path:
    return _write_text(
        root / "harness.c",
        "\n".join(
            [
                "#include <stdio.h>",
                "int main(int argc, char **argv) {",
                "  printf(\"stub harness\\n\");",
                "  return 0;",
                "}",
            ]
        )
        + "\n",
    )


def _make_seed_workdir(root: Path) -> Path:
    seed_workdir = root / "seed_workdir"
    _write_text(seed_workdir / "input" / "seed_00.prog", "openat$KVM(0)\n")
    _write_text(seed_workdir / "relations" / "bridge_seed.relations", "openat$KVM,ioctl$KVM_CREATE_VM\n")
    _write_text(seed_workdir / "bias.json", json.dumps({"candidate_id": "cand_demo"}) + "\n")
    _write_text(
        seed_workdir / "imported_seed.json",
        json.dumps(
            {
                "candidate_id": "cand_demo",
                "entries": [{"entry_func": "kvm_vcpu_ioctl"}],
                "debug": {
                    "loc0": {"function": "demo_free", "file": "arch/arm64/kvm/demo.c", "line": 10},
                    "loc1": {"function": "demo_use", "file": "arch/arm64/kvm/demo.c", "line": 20},
                },
            }
        )
        + "\n",
    )
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
            WITNESS_SCRIPT,
            BUILD_HARNESS_SCRIPT,
            RUN_HARNESS_SCRIPT,
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

    def test_run_script_emits_verdict_after_successful_run(self) -> None:
        assets = _make_runtime_assets(self.tmpdir / "run-script-verdict")
        syz_dir = _make_syz_dir(self.tmpdir / "run-script-verdict", direct_layout=True)
        output_dir = self.tmpdir / "verdict-output"
        fake_bin = self.tmpdir / "verdict-fake-bin"
        fake_bin.mkdir(parents=True, exist_ok=True)
        fake_cargo = fake_bin / "cargo"
        fake_cargo.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import pathlib",
                    "import sys",
                    "args = sys.argv[1:]",
                    "if '-o' in args:",
                    "    out = pathlib.Path(args[args.index('-o') + 1])",
                    "    out.mkdir(parents=True, exist_ok=True)",
                    "print('fake cargo invoked')",
                ]
            ),
            encoding="utf-8",
        )
        fake_cargo.chmod(0o755)

        env = self._base_env()
        env["PATH"] = f"{fake_bin}:{env['PATH']}"

        proc = subprocess.run(
            [
                "bash",
                str(RUN_SCRIPT),
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
        verdict_path = output_dir / "verdict.json"
        self.assertTrue(verdict_path.is_file())
        verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
        self.assertEqual(verdict["candidate_id"], "cand_demo")
        self.assertEqual(verdict["verdict"], "REACHED_NO_CRASH")
        self.assertIn("Verdict:", proc.stdout)

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

    def test_run_witness_script_executes_remote_witness_and_emits_verdict(self) -> None:
        case_dir = self.tmpdir / "run-witness"
        inputs = _make_candidate_and_witness(case_dir)
        syz_dir = _make_syz_dir(case_dir, direct_layout=True)
        output_dir = case_dir / "output"
        fake_bin = case_dir / "fake-bin"
        fake_bin.mkdir(parents=True, exist_ok=True)
        remote_root = case_dir / "remote-root"
        remote_root.mkdir(parents=True, exist_ok=True)
        remote_bin = case_dir / "remote-bin"
        remote_bin.mkdir(parents=True, exist_ok=True)
        remote_dir = remote_root / "workspace"
        dmesg_file = remote_root / "dmesg.log"
        dmesg_file.write_text("boot ok\n", encoding="utf-8")

        _write_executable_text(
            syz_dir / "syz-execprog",
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import os",
                    "from pathlib import Path",
                    "dmesg_path = Path(os.environ['FAKE_REMOTE_DMESG'])",
                    "current = dmesg_path.read_text(encoding='utf-8') if dmesg_path.exists() else ''",
                    "crash_log = os.environ.get('FAKE_REMOTE_CRASH_LOG', '')",
                    "if crash_log and crash_log not in current:",
                    "    dmesg_path.write_text(current + crash_log, encoding='utf-8')",
                    "print('fake execprog ran')",
                ]
            ),
        )
        _write_executable_text(
            remote_bin / "dmesg",
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import os",
                    "import sys",
                    "from pathlib import Path",
                    "path = Path(os.environ['FAKE_REMOTE_DMESG'])",
                    "if path.exists():",
                    "    sys.stdout.write(path.read_text(encoding='utf-8'))",
                ]
            ),
        )
        _write_executable_text(
            fake_bin / "ssh",
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import os",
                    "import shlex",
                    "import subprocess",
                    "import sys",
                    "args = sys.argv[1:]",
                    "i = 0",
                    "while i < len(args):",
                    "    arg = args[i]",
                    "    if arg in {'-F', '-i', '-p', '-P'}:",
                    "        i += 2",
                    "        continue",
                    "    if arg == '-o':",
                    "        i += 2",
                    "        continue",
                    "    if arg.startswith('-'):",
                    "        i += 1",
                    "        continue",
                    "    break",
                    "target = args[i]",
                    "command = args[i + 1:]",
                    "env = dict(os.environ)",
                    "env['PATH'] = env['FAKE_REMOTE_BIN'] + os.pathsep + env.get('PATH', '')",
                    "stdin_data = sys.stdin.read()",
                    "if not command:",
                    "    sys.exit(0)",
                    "if command[0] == 'bash':",
                    "    proc = subprocess.run(command, input=stdin_data, text=True, cwd=env['FAKE_REMOTE_ROOT'], env=env)",
                    "else:",
                    "    shell_cmd = command[0] if len(command) == 1 else shlex.join(command)",
                    "    proc = subprocess.run(['bash', '-c', shell_cmd], input=stdin_data, text=True, cwd=env['FAKE_REMOTE_ROOT'], env=env)",
                    "sys.exit(proc.returncode)",
                ]
            ),
        )
        _write_executable_text(
            fake_bin / "scp",
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import os",
                    "import shutil",
                    "import sys",
                    "from pathlib import Path",
                    "args = sys.argv[1:]",
                    "i = 0",
                    "values = []",
                    "while i < len(args):",
                    "    arg = args[i]",
                    "    if arg in {'-F', '-i', '-P'}:",
                    "        i += 2",
                    "        continue",
                    "    if arg == '-o':",
                    "        i += 2",
                    "        continue",
                    "    if arg.startswith('-'):",
                    "        i += 1",
                    "        continue",
                    "    values.append(arg)",
                    "    i += 1",
                    "src, dst = values",
                    "def remote_path(spec):",
                    "    if ':' not in spec:",
                    "        return None",
                    "    left, right = spec.split(':', 1)",
                    "    if '@' not in left:",
                    "        return None",
                    "    return Path(right)",
                    "src_remote = remote_path(src)",
                    "dst_remote = remote_path(dst)",
                    "if src_remote is not None and dst_remote is None:",
                    "    target = Path(dst)",
                    "    target.parent.mkdir(parents=True, exist_ok=True)",
                    "    shutil.copy2(src_remote, target)",
                    "elif src_remote is None and dst_remote is not None:",
                    "    dst_remote.parent.mkdir(parents=True, exist_ok=True)",
                    "    shutil.copy2(Path(src), dst_remote)",
                    "else:",
                    "    raise SystemExit(2)",
                ]
            ),
        )

        env = self._base_env()
        env["PATH"] = f"{fake_bin}:{env['PATH']}"
        env["FAKE_REMOTE_ROOT"] = str(remote_root)
        env["FAKE_REMOTE_BIN"] = str(remote_bin)
        env["FAKE_REMOTE_DMESG"] = str(dmesg_file)
        env["FAKE_REMOTE_CRASH_LOG"] = MATCHING_WITNESS_LOG

        proc = subprocess.run(
            [
                "bash",
                str(WITNESS_SCRIPT),
                "--witness",
                str(inputs["witness"]),
                "--candidate",
                str(inputs["candidate"]),
                "--target-host",
                "fake-target",
                "--ssh-key",
                str(_write_text(case_dir / "id_rsa", "fake-key")),
                "--syz-dir",
                str(syz_dir),
                "--output-dir",
                str(output_dir),
                "--remote-dir",
                str(remote_dir),
                "--runs",
                "2",
            ],
            cwd=MOCK_ROOT,
            capture_output=True,
            text=True,
            env=env,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        verdict = json.loads((output_dir / "verdict.json").read_text(encoding="utf-8"))
        self.assertEqual(verdict["verdict"], "CONFIRMED")
        self.assertEqual(verdict["execution"]["execution_mode"], "witness_remote")
        self.assertEqual(verdict["execution"]["runs"], 2)
        self.assertTrue((output_dir / "crashes" / "raw_logs" / "witness-dmesg.log").is_file())
        self.assertTrue((output_dir / "logs" / "remote-dmesg-delta.log").is_file())
        self.assertIn("Verdict:", proc.stdout)

    def test_run_harness_script_executes_timing_sweep_and_emits_aggregate_verdict(self) -> None:
        case_dir = self.tmpdir / "run-harness"
        inputs = _make_candidate_and_witness(case_dir)
        harness_source = _make_harness_source(case_dir)
        output_dir = case_dir / "output"
        fake_bin = case_dir / "fake-bin"
        fake_bin.mkdir(parents=True, exist_ok=True)
        remote_root = case_dir / "remote-root"
        remote_root.mkdir(parents=True, exist_ok=True)
        remote_bin = case_dir / "remote-bin"
        remote_bin.mkdir(parents=True, exist_ok=True)
        remote_dir = remote_root / "workspace"
        dmesg_file = remote_root / "dmesg.log"
        dmesg_file.write_text("boot ok\n", encoding="utf-8")

        _write_executable_text(
            remote_bin / "dmesg",
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import os",
                    "import sys",
                    "from pathlib import Path",
                    "path = Path(os.environ['FAKE_REMOTE_DMESG'])",
                    "if path.exists():",
                    "    sys.stdout.write(path.read_text(encoding='utf-8'))",
                ]
            ),
        )
        _write_executable_text(
            remote_bin / "gcc",
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import os",
                    "from pathlib import Path",
                    "import sys",
                    "args = sys.argv[1:]",
                    "output = Path(args[args.index('-o') + 1])",
                    "output.parent.mkdir(parents=True, exist_ok=True)",
                    "payload = '\\n'.join([",
                    "    '#!/usr/bin/env python3',",
                    "    'import os',",
                    "    'import sys',",
                    "    'from pathlib import Path',",
                    "    \"timing = sys.argv[1] if len(sys.argv) > 1 else '0'\",",
                    "    \"dmesg_path = Path(os.environ['FAKE_REMOTE_DMESG'])\",",
                    "    \"current = dmesg_path.read_text(encoding=\\'utf-8\\') if dmesg_path.exists() else ''\",",
                    "    \"if os.environ.get('FAKE_HARNESS_SETUP_FAIL_TIMING') == timing:\",",
                    "    \"    print('HARNESS: setup_failed=1 stage=fake errno=5')\",",
                    "    \"    sys.exit(2)\",",
                    "    \"print('HARNESS: candidate_id=cand_demo')\",",
                    "    \"print(f'HARNESS: timing_us={timing}')\",",
                    "    \"print('HARNESS: setup_ok=1')\",",
                    "    \"print('HARNESS: event=free entered=1 thread=0')\",",
                    "    \"print('HARNESS: event=use entered=1 thread=1')\",",
                    "    \"print('HARNESS: candidate_reached=1')\",",
                    "    \"print('HARNESS: timing_window_entered=1')\",",
                    "    \"print('HARNESS: execution_completed=1')\",",
                    "    \"print('HARNESS: reached_no_crash=1')\",",
                    "    \"crash_timing = os.environ.get('FAKE_HARNESS_CRASH_TIMING')\",",
                    "    \"crash_log = os.environ.get('FAKE_REMOTE_CRASH_LOG', '')\",",
                    "    \"if crash_timing == timing and crash_log and crash_log not in current:\",",
                    "    \"    dmesg_path.write_text(current + crash_log, encoding=\\'utf-8\\')\",",
                    "]) + '\\n'",
                    "output.write_text(payload, encoding='utf-8')",
                    "output.chmod(0o755)",
                ]
            ),
        )
        _write_executable_text(
            fake_bin / "ssh",
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import os",
                    "import shlex",
                    "import subprocess",
                    "import sys",
                    "args = sys.argv[1:]",
                    "i = 0",
                    "while i < len(args):",
                    "    arg = args[i]",
                    "    if arg in {'-F', '-i', '-p', '-P'}:",
                    "        i += 2",
                    "        continue",
                    "    if arg == '-o':",
                    "        i += 2",
                    "        continue",
                    "    if arg.startswith('-'):",
                    "        i += 1",
                    "        continue",
                    "    break",
                    "target = args[i]",
                    "command = args[i + 1:]",
                    "env = dict(os.environ)",
                    "env['PATH'] = env['FAKE_REMOTE_BIN'] + os.pathsep + env.get('PATH', '')",
                    "stdin_data = sys.stdin.read()",
                    "if not command:",
                    "    sys.exit(0)",
                    "if command[0] == 'bash':",
                    "    proc = subprocess.run(command, input=stdin_data, text=True, cwd=env['FAKE_REMOTE_ROOT'], env=env)",
                    "else:",
                    "    shell_cmd = command[0] if len(command) == 1 else shlex.join(command)",
                    "    proc = subprocess.run(['bash', '-c', shell_cmd], input=stdin_data, text=True, cwd=env['FAKE_REMOTE_ROOT'], env=env)",
                    "sys.exit(proc.returncode)",
                ]
            ),
        )
        _write_executable_text(
            fake_bin / "scp",
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import shutil",
                    "import sys",
                    "from pathlib import Path",
                    "args = sys.argv[1:]",
                    "i = 0",
                    "values = []",
                    "while i < len(args):",
                    "    arg = args[i]",
                    "    if arg in {'-F', '-i', '-P'}:",
                    "        i += 2",
                    "        continue",
                    "    if arg == '-o':",
                    "        i += 2",
                    "        continue",
                    "    if arg.startswith('-'):",
                    "        i += 1",
                    "        continue",
                    "    values.append(arg)",
                    "    i += 1",
                    "src, dst = values",
                    "def remote_path(spec):",
                    "    if ':' not in spec:",
                    "        return None",
                    "    left, right = spec.split(':', 1)",
                    "    if '@' not in left:",
                    "        return None",
                    "    return Path(right)",
                    "src_remote = remote_path(src)",
                    "dst_remote = remote_path(dst)",
                    "if src_remote is not None and dst_remote is None:",
                    "    target = Path(dst)",
                    "    target.parent.mkdir(parents=True, exist_ok=True)",
                    "    shutil.copy2(src_remote, target)",
                    "elif src_remote is None and dst_remote is not None:",
                    "    dst_remote.parent.mkdir(parents=True, exist_ok=True)",
                    "    shutil.copy2(Path(src), dst_remote)",
                    "else:",
                    "    raise SystemExit(2)",
                ]
            ),
        )

        env = self._base_env()
        env["PATH"] = f"{fake_bin}:{env['PATH']}"
        env["FAKE_REMOTE_ROOT"] = str(remote_root)
        env["FAKE_REMOTE_BIN"] = str(remote_bin)
        env["FAKE_REMOTE_DMESG"] = str(dmesg_file)
        env["FAKE_REMOTE_CRASH_LOG"] = MATCHING_WITNESS_LOG
        env["FAKE_HARNESS_CRASH_TIMING"] = "1000"

        proc = subprocess.run(
            [
                "bash",
                str(RUN_HARNESS_SCRIPT),
                "--harness",
                str(harness_source),
                "--candidate",
                str(inputs["candidate"]),
                "--target-host",
                "fake-target",
                "--ssh-key",
                str(_write_text(case_dir / "id_rsa", "fake-key")),
                "--output-dir",
                str(output_dir),
                "--remote-dir",
                str(remote_dir),
                "--timing-range",
                "0,1000",
                "--runs-per-timing",
                "2",
            ],
            cwd=MOCK_ROOT,
            capture_output=True,
            text=True,
            env=env,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        verdict = json.loads((output_dir / "verdict.json").read_text(encoding="utf-8"))
        self.assertEqual(verdict["verdict"], "CONFIRMED")
        self.assertEqual(verdict["execution"]["execution_mode"], "harness_timing_sweep")
        self.assertEqual(verdict["execution"]["best_timing_us"], 1000)
        self.assertEqual(verdict["execution"]["runs_total"], 4)
        self.assertTrue((output_dir / "runs" / "1000us" / "run-1" / "result.json").is_file())
        self.assertTrue((output_dir / "crashes" / "raw_logs" / "1000us-run-1-dmesg-delta.log").is_file())
        self.assertIn("Aggregate verdict:", proc.stdout)


if __name__ == "__main__":
    unittest.main()
