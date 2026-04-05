"""Inject a .prog file and syz-execprog into the guest, execute, capture output.

Uses SCP to copy files and SSH to run syz-execprog inside the guest.
Keeps the interface small: one function that does copy + execute + return output.
"""

from __future__ import annotations

import pathlib
import subprocess
from typing import Any


def _scp_cmd(port: int, ssh_key: pathlib.Path) -> list[str]:
    """Base SCP command with standard options."""
    return [
        "scp",
        "-O",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=20",
        "-o", "LogLevel=ERROR",
        "-i", str(ssh_key),
        "-P", str(port),
    ]


def _ssh_cmd(port: int, ssh_key: pathlib.Path) -> list[str]:
    """Base SSH command with standard options."""
    return [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=20",
        "-o", "LogLevel=ERROR",
        "-i", str(ssh_key),
        "-p", str(port),
        "root@127.0.0.1",
    ]


def copy_to_guest(
    local_path: pathlib.Path,
    remote_path: str,
    ssh_port: int,
    ssh_key: pathlib.Path,
    timeout: float = 60,
) -> dict:
    """SCP a file into the guest. Returns {"ok": bool, "error": str|None}."""
    cmd = _scp_cmd(ssh_port, ssh_key) + [
        str(local_path),
        f"root@127.0.0.1:{remote_path}",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            return {"ok": False, "error": f"scp failed (rc={result.returncode}): {result.stderr[:300]}"}
        return {"ok": True, "error": None}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"scp timed out after {timeout}s"}
    except OSError as exc:
        return {"ok": False, "error": f"scp failed: {exc}"}


def execute_prog(
    syz_execprog: pathlib.Path,
    prog_file: pathlib.Path,
    ssh_port: int,
    ssh_key: pathlib.Path,
    executor_path: str | None = None,
    timeout: float = 120,
) -> dict:
    """Copy syz-execprog + .prog to guest, execute, return output.

    Args:
        executor_path: Guest-side path to syz-executor binary. If provided,
            passed as -executor=<path> to syz-execprog. If the guest already
            has syz-executor installed (e.g. /root/syzkaller/syz-executor),
            pass that path here.

    Returns:
        {
            "ok": bool,
            "stdout": str,
            "stderr": str,
            "exit_code": int | None,
            "error": str | None,
            "copy_results": list[dict],
        }
    """
    copy_results = []

    # Copy syz-execprog binary.
    r = copy_to_guest(syz_execprog, "/root/syz-execprog", ssh_port, ssh_key)
    copy_results.append({"file": "syz-execprog", **r})
    if not r["ok"]:
        return {
            "ok": False, "stdout": "", "stderr": "",
            "exit_code": None, "error": r["error"],
            "copy_results": copy_results,
        }

    # Make it executable.
    ssh = _ssh_cmd(ssh_port, ssh_key)
    try:
        subprocess.run(ssh + ["chmod", "+x", "/root/syz-execprog"],
                        capture_output=True, timeout=10)
    except (subprocess.TimeoutExpired, OSError):
        pass  # Best-effort.

    # Copy .prog file.
    r = copy_to_guest(prog_file, "/root/seed.prog", ssh_port, ssh_key)
    copy_results.append({"file": str(prog_file.name), **r})
    if not r["ok"]:
        return {
            "ok": False, "stdout": "", "stderr": "",
            "exit_code": None, "error": r["error"],
            "copy_results": copy_results,
        }

    # Execute.
    exec_args = ["/root/syz-execprog", "-repeat=1", "-threaded=0"]
    if executor_path:
        exec_args.append(f"-executor={executor_path}")
    exec_args.append("/root/seed.prog")
    exec_cmd = ssh + exec_args
    try:
        result = subprocess.run(exec_cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "ok": True,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
            "error": None,
            "copy_results": copy_results,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False, "stdout": "", "stderr": "",
            "exit_code": None,
            "error": f"syz-execprog timed out after {timeout}s",
            "copy_results": copy_results,
        }
    except OSError as exc:
        return {
            "ok": False, "stdout": "", "stderr": "",
            "exit_code": None, "error": f"ssh exec failed: {exc}",
            "copy_results": copy_results,
        }


def build_inject_cmd(
    ssh_port: int,
    ssh_key: pathlib.Path,
) -> list[str]:
    """Return the SSH command prefix — useful for testing command construction."""
    return _ssh_cmd(ssh_port, ssh_key)


def build_scp_cmd(
    local_path: pathlib.Path,
    remote_path: str,
    ssh_port: int,
    ssh_key: pathlib.Path,
) -> list[str]:
    """Return the full SCP command — useful for testing command construction."""
    return _scp_cmd(ssh_port, ssh_key) + [str(local_path), f"root@127.0.0.1:{remote_path}"]
