"""QEMU TCG lifecycle manager for one-shot arm64 validation.

Boots a QEMU aarch64 virt machine under TCG (software emulation),
waits for SSH readiness, and provides clean shutdown with force-kill fallback.
"""

from __future__ import annotations

import pathlib
import socket
import subprocess
import time
from typing import Any

# Defaults — can be overridden per-call.
DEFAULT_SSH_PORT = 10022
DEFAULT_MEM_MB = 2048
DEFAULT_CPU = "cortex-a57"
DEFAULT_BOOT_TIMEOUT = 180  # seconds — TCG is slow
DEFAULT_SSH_POLL_INTERVAL = 3  # seconds between SSH probes


def build_qemu_cmd(
    kernel: pathlib.Path,
    disk_image: pathlib.Path,
    ssh_port: int = DEFAULT_SSH_PORT,
    mem_mb: int = DEFAULT_MEM_MB,
    cpu: str = DEFAULT_CPU,
    console_log: pathlib.Path | None = None,
    extra_append: str = "",
) -> list[str]:
    """Build the qemu-system-aarch64 command line.

    Returns a list suitable for subprocess.Popen.
    """
    append_parts = [
        "root=/dev/vda1",
        "console=ttyAMA0",
        "kasan.fault=panic",
    ]
    if extra_append:
        append_parts.append(extra_append)

    cmd = [
        "qemu-system-aarch64",
        "-machine", "virt",
        "-accel", "tcg",
        "-cpu", cpu,
        "-m", str(mem_mb),
        "-nographic",
        "-kernel", str(kernel),
        "-drive", f"if=virtio,format=qcow2,file={disk_image}",
        "-append", " ".join(append_parts),
        "-netdev", f"user,id=net0,hostfwd=tcp:127.0.0.1:{ssh_port}-:22",
        "-device", "virtio-net-pci,netdev=net0",
        "-no-reboot",
    ]

    if console_log:
        cmd += ["-serial", f"file:{console_log}"]

    return cmd


def wait_for_ssh(
    host: str = "127.0.0.1",
    port: int = DEFAULT_SSH_PORT,
    timeout: float = DEFAULT_BOOT_TIMEOUT,
    poll_interval: float = DEFAULT_SSH_POLL_INTERVAL,
) -> dict:
    """Poll until SSH port accepts a TCP connection or timeout expires.

    Returns {"ok": bool, "elapsed": float, "error": str|None}.
    """
    start = time.monotonic()
    deadline = start + timeout
    last_error = None

    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                elapsed = time.monotonic() - start
                return {"ok": True, "elapsed": round(elapsed, 1), "error": None}
        except (ConnectionRefusedError, OSError, socket.timeout) as exc:
            last_error = str(exc)
        time.sleep(poll_interval)

    elapsed = time.monotonic() - start
    return {"ok": False, "elapsed": round(elapsed, 1), "error": f"SSH not ready after {timeout}s: {last_error}"}


def boot_vm(
    kernel: pathlib.Path,
    disk_image: pathlib.Path,
    ssh_port: int = DEFAULT_SSH_PORT,
    mem_mb: int = DEFAULT_MEM_MB,
    console_log: pathlib.Path | None = None,
    boot_timeout: float = DEFAULT_BOOT_TIMEOUT,
) -> dict:
    """Start QEMU and wait for SSH readiness.

    Returns:
        {
            "ok": bool,
            "process": subprocess.Popen | None,
            "ssh_ready": dict,
            "qemu_cmd": list[str],
            "error": str | None,
        }
    """
    cmd = build_qemu_cmd(
        kernel=kernel,
        disk_image=disk_image,
        ssh_port=ssh_port,
        mem_mb=mem_mb,
        console_log=console_log,
    )

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        return {
            "ok": False,
            "process": None,
            "ssh_ready": {"ok": False, "elapsed": 0, "error": str(exc)},
            "qemu_cmd": cmd,
            "error": f"Failed to start QEMU: {exc}",
        }

    # Give QEMU a moment to start before polling SSH.
    time.sleep(1)

    # Check that QEMU didn't exit immediately.
    if proc.poll() is not None:
        stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        return {
            "ok": False,
            "process": None,
            "ssh_ready": {"ok": False, "elapsed": 0, "error": "QEMU exited immediately"},
            "qemu_cmd": cmd,
            "error": f"QEMU exited with code {proc.returncode}: {stderr[:500]}",
        }

    ssh_result = wait_for_ssh(port=ssh_port, timeout=boot_timeout)

    return {
        "ok": ssh_result["ok"],
        "process": proc,
        "ssh_ready": ssh_result,
        "qemu_cmd": cmd,
        "error": ssh_result["error"],
    }


def shutdown_vm(
    proc: subprocess.Popen,
    ssh_port: int = DEFAULT_SSH_PORT,
    ssh_key: pathlib.Path | None = None,
    graceful_timeout: float = 15,
) -> dict:
    """Shut down the VM: try SSH poweroff first, then SIGTERM, then SIGKILL.

    Returns {"method": str, "exit_code": int|None}.
    """
    # Try graceful SSH poweroff.
    if ssh_key is not None:
        try:
            subprocess.run(
                _ssh_cmd(ssh_port, ssh_key) + ["poweroff"],
                capture_output=True, timeout=5,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass

    # Wait for graceful exit.
    try:
        proc.wait(timeout=graceful_timeout)
        return {"method": "ssh_poweroff", "exit_code": proc.returncode}
    except subprocess.TimeoutExpired:
        pass

    # SIGTERM.
    proc.terminate()
    try:
        proc.wait(timeout=5)
        return {"method": "sigterm", "exit_code": proc.returncode}
    except subprocess.TimeoutExpired:
        pass

    # SIGKILL.
    proc.kill()
    proc.wait(timeout=5)
    return {"method": "sigkill", "exit_code": proc.returncode}


def _ssh_cmd(port: int, ssh_key: pathlib.Path) -> list[str]:
    """Build base SSH command with standard options."""
    return [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=5",
        "-o", "LogLevel=ERROR",
        "-i", str(ssh_key),
        "-p", str(port),
        "root@127.0.0.1",
    ]
