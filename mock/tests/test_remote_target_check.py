from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


MOCK_ROOT = Path(__file__).resolve().parents[1]
REMOTE_CHECK_SCRIPT = MOCK_ROOT / "scripts" / "check_remote_target.sh"


def _write_text(path: Path, content: str = "stub") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_executable(path: Path, content: str) -> Path:
    _write_text(path, content)
    path.chmod(0o755)
    return path


def _make_syz_dir(root: Path) -> Path:
    syz_dir = root / "syz-bin"
    _write_text(syz_dir / "bin" / "linux_arm64" / "syz-executor")
    _write_text(syz_dir / "bin" / "syz-execprog")
    return syz_dir


class RemoteTargetCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="remote-target-check-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_shell_script_has_valid_syntax(self) -> None:
        proc = subprocess.run(["bash", "-n", str(REMOTE_CHECK_SCRIPT)], cwd=MOCK_ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_remote_target_checker_accepts_supported_remote_target(self) -> None:
        fake_bin = self.tmpdir / "fake-bin"
        fake_bin.mkdir(parents=True, exist_ok=True)
        remote_root = self.tmpdir / "remote-root"
        remote_root.mkdir(parents=True, exist_ok=True)
        remote_bin = self.tmpdir / "remote-bin"
        remote_bin.mkdir(parents=True, exist_ok=True)
        dmesg_file = remote_root / "dmesg.log"
        dmesg_file.write_text("boot ok\n", encoding="utf-8")
        syz_dir = _make_syz_dir(self.tmpdir)
        ssh_key = _write_text(self.tmpdir / "id_rsa", "fake-key")

        _write_executable(
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
        _write_executable(remote_bin / "gcc", "#!/usr/bin/env bash\nexit 0\n")
        _write_executable(
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

        env = dict(os.environ)
        env["PATH"] = f"{fake_bin}:{env['PATH']}"
        env["FAKE_REMOTE_ROOT"] = str(remote_root)
        env["FAKE_REMOTE_BIN"] = str(remote_bin)
        env["FAKE_REMOTE_DMESG"] = str(dmesg_file)

        proc = subprocess.run(
            [
                "bash",
                str(REMOTE_CHECK_SCRIPT),
                "--mode",
                "both",
                "--target-host",
                "fake-target",
                "--ssh-key",
                str(ssh_key),
                "--syz-dir",
                str(syz_dir),
            ],
            cwd=MOCK_ROOT,
            capture_output=True,
            text=True,
            env=env,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("ok: ssh connectivity", proc.stdout)
        self.assertIn("ok: remote temp dir writable", proc.stdout)
        self.assertIn("ok: remote dmesg readable", proc.stdout)
        self.assertIn("ok: remote gcc present for harness mode", proc.stdout)
        self.assertIn("ok: local syz-executor available for witness upload", proc.stdout)
        self.assertIn("ok: local syz-execprog available for witness upload", proc.stdout)


if __name__ == "__main__":
    unittest.main()
