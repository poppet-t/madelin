from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "_bridge_python.sh"


def _write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_executable(path: Path, content: str) -> Path:
    _write_text(path, content)
    path.chmod(0o755)
    return path


def _select_bridge_python(bridge_root: Path, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    command = f"source {HELPER!s}; select_bridge_python {bridge_root!s}"
    return subprocess.run(
        ["bash", "-lc", command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


class BridgePythonSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="bridge-python-selection-"))
        _write_text(self.tmpdir / "scripts" / "check_env.py", "print('stub check env')\n")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_selects_first_environment_that_passes_preflight(self) -> None:
        _write_executable(self.tmpdir / ".venv_ci" / "bin" / "python", "#!/usr/bin/env bash\nexit 1\n")
        good_python = _write_executable(self.tmpdir / ".venv" / "bin" / "python", "#!/usr/bin/env bash\nexit 0\n")
        _write_executable(self.tmpdir / ".venv_sys" / "bin" / "python", "#!/usr/bin/env bash\nexit 0\n")

        proc = _select_bridge_python(self.tmpdir)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), str(good_python))

    def test_python_override_wins_when_executable(self) -> None:
        override = _write_executable(self.tmpdir / "custom-python", "#!/usr/bin/env bash\nexit 0\n")
        env = dict(os.environ)
        env["PYTHON"] = str(override)

        proc = _select_bridge_python(self.tmpdir, env=env)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), str(override))


if __name__ == "__main__":
    unittest.main()
