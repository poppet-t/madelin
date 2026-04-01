"""Collect dmesg and execution logs from the guest VM.

Pulls dmesg over SSH, extracts KASAN/UAF sections if present,
and writes raw + filtered logs to the output directory.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
from typing import Any


def _ssh_cmd(port: int, ssh_key: pathlib.Path) -> list[str]:
    """Base SSH command."""
    return [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=10",
        "-o", "LogLevel=ERROR",
        "-i", str(ssh_key),
        "-p", str(port),
        "root@127.0.0.1",
    ]


def collect_dmesg(
    ssh_port: int,
    ssh_key: pathlib.Path,
    timeout: float = 30,
) -> dict:
    """Pull dmesg from guest. Returns {"ok": bool, "dmesg": str, "error": str|None}."""
    cmd = _ssh_cmd(ssh_port, ssh_key) + ["dmesg"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"ok": True, "dmesg": result.stdout, "error": None}
    except subprocess.TimeoutExpired:
        return {"ok": False, "dmesg": "", "error": f"dmesg collection timed out after {timeout}s"}
    except OSError as exc:
        return {"ok": False, "dmesg": "", "error": f"dmesg collection failed: {exc}"}


def extract_kasan(dmesg: str) -> str | None:
    """Extract KASAN report section from dmesg text.

    Returns the extracted section or None if no KASAN report found.
    """
    if not dmesg:
        return None

    lines = dmesg.split("\n")
    kasan_lines: list[str] = []
    in_report = False

    for line in lines:
        if re.search(r"BUG: KASAN:", line, re.IGNORECASE):
            in_report = True
        if in_report:
            kasan_lines.append(line)
            # KASAN reports end with a separator or blank after the stack trace.
            if re.search(r"^=+$", line.strip()) and len(kasan_lines) > 3:
                break

    if not kasan_lines:
        return None

    return "\n".join(kasan_lines)


def save_logs(
    out_dir: pathlib.Path,
    dmesg: str,
    kasan_excerpt: str | None,
    execprog_stdout: str = "",
    execprog_stderr: str = "",
) -> dict:
    """Write collected logs to the output directory.

    Returns {"files_written": list[str]}.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    dmesg_path = out_dir / "guest_dmesg.txt"
    dmesg_path.write_text(dmesg)
    written.append(str(dmesg_path))

    if kasan_excerpt:
        crash_path = out_dir / "crash_log.txt"
        crash_path.write_text(kasan_excerpt)
        written.append(str(crash_path))

    if execprog_stdout:
        (out_dir / "execprog_stdout.txt").write_text(execprog_stdout)
        written.append(str(out_dir / "execprog_stdout.txt"))

    if execprog_stderr:
        (out_dir / "execprog_stderr.txt").write_text(execprog_stderr)
        written.append(str(out_dir / "execprog_stderr.txt"))

    return {"files_written": written}
