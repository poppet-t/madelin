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
DEFAULT_SSH_COMMAND_TIMEOUT = 30
DEFAULT_SSH_CONNECT_TIMEOUT = 20


def classify_boot_failure(
    *,
    console_excerpt: list[str],
    last_banner: dict[str, Any] | None = None,
    last_ssh: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = "\n".join(console_excerpt)
    if "Requested init " in text and "failed (error -2)" in text:
        return {
            "failure_class": "custom_init_missing",
            "reason": "Kernel was asked to execute a custom init path that does not exist in the guest image.",
        }
    if "Kernel panic - not syncing" in text:
        return {
            "failure_class": "kernel_panic_before_userspace",
            "reason": "Kernel panicked before reaching a stable userspace boot.",
        }
    if "Entering emergency mode" in text or "emergency mode" in text:
        return {
            "failure_class": "systemd_emergency_mode",
            "reason": "Systemd entered emergency mode during guest boot.",
        }
    if "Timed out waiting for device" in text or "Dependency failed for" in text or "Job " in text:
        return {
            "failure_class": "systemd_boot_stall",
            "reason": "Systemd boot stalled on guest image dependencies or device units.",
        }
    if last_ssh and last_ssh.get("failure_class"):
        return {
            "failure_class": last_ssh["failure_class"],
            "reason": last_ssh.get("error") or "SSH command failed during readiness probing.",
        }
    if last_banner:
        if last_banner.get("connected") and last_banner.get("error") == "banner timeout":
            return {
                "failure_class": "ssh_banner_timeout",
                "reason": "Guest accepted TCP on port 22 but did not emit a raw SSH banner.",
            }
        if not last_banner.get("connected"):
            return {
                "failure_class": "ssh_port_unreachable",
                "reason": last_banner.get("error") or "Guest never accepted TCP on port 22.",
            }
    return {
        "failure_class": "ssh_readiness_failure",
        "reason": "Guest boot did not reach a usable non-interactive SSH session.",
    }


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
    ]

    seed_image = disk_image.parent / "seed.img"
    if seed_image.exists():
        cmd += ["-drive", f"if=virtio,format=raw,file={seed_image}"]

    cmd += [
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


def probe_ssh_banner(
    host: str = "127.0.0.1",
    port: int = DEFAULT_SSH_PORT,
    timeout: float = 3,
) -> dict[str, Any]:
    """Attempt a raw TCP connect and collect the SSH banner if one appears."""
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            try:
                banner = sock.recv(256)
            except socket.timeout:
                return {
                    "ok": False,
                    "elapsed": round(time.monotonic() - started, 3),
                    "error": "banner timeout",
                    "banner": "",
                    "connected": True,
                }
            banner_text = banner.decode(errors="replace").strip()
            return {
                "ok": bool(banner_text.startswith("SSH-")),
                "elapsed": round(time.monotonic() - started, 3),
                "error": None if banner_text.startswith("SSH-") else f"unexpected banner: {banner_text[:80]}",
                "banner": banner_text,
                "connected": True,
            }
    except (ConnectionRefusedError, OSError, socket.timeout) as exc:
        return {
            "ok": False,
            "elapsed": round(time.monotonic() - started, 3),
            "error": str(exc),
            "banner": "",
            "connected": False,
        }


def probe_ssh_command(
    *,
    ssh_key: pathlib.Path,
    host: str = "127.0.0.1",
    port: int = DEFAULT_SSH_PORT,
    timeout: float = DEFAULT_SSH_COMMAND_TIMEOUT,
    command: str = "true",
) -> dict[str, Any]:
    """Attempt a real non-interactive SSH command."""
    started = time.monotonic()
    cmd = _ssh_cmd(port, ssh_key)
    cmd[-1] = f"root@{host}"
    cmd.append(command)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        stderr = result.stderr.strip()
        failure_class = None
        if result.returncode != 0:
            if "Permission denied" in stderr:
                failure_class = "ssh_auth_failure"
            elif "banner exchange" in stderr:
                failure_class = "ssh_banner_timeout"
            else:
                failure_class = "ssh_command_failed"
        return {
            "ok": result.returncode == 0,
            "elapsed": round(time.monotonic() - started, 3),
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "error": None if result.returncode == 0 else stderr or f"ssh exited with rc={result.returncode}",
            "failure_class": failure_class,
            "cmd": cmd,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "elapsed": round(time.monotonic() - started, 3),
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "error": f"ssh command timed out after {timeout}s",
            "failure_class": "ssh_command_timeout",
            "cmd": cmd,
        }
    except OSError as exc:
        return {
            "ok": False,
            "elapsed": round(time.monotonic() - started, 3),
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "error": str(exc),
            "failure_class": "ssh_command_failed",
            "cmd": cmd,
        }


def _read_console_excerpt(console_log: pathlib.Path | None, max_lines: int = 80) -> list[str]:
    if console_log is None or not console_log.exists():
        return []
    lines = console_log.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-max_lines:]


def wait_for_ssh_command(
    *,
    ssh_key: pathlib.Path,
    host: str = "127.0.0.1",
    port: int = DEFAULT_SSH_PORT,
    timeout: float = DEFAULT_BOOT_TIMEOUT,
    poll_interval: float = DEFAULT_SSH_POLL_INTERVAL,
    console_log: pathlib.Path | None = None,
) -> dict[str, Any]:
    """Poll until the guest accepts a real SSH command or timeout expires."""
    start = time.monotonic()
    deadline = start + timeout
    timeline: list[dict[str, Any]] = []
    last_banner: dict[str, Any] | None = None
    last_ssh: dict[str, Any] | None = None

    while time.monotonic() < deadline:
        elapsed = round(time.monotonic() - start, 1)
        banner = probe_ssh_banner(host=host, port=port, timeout=2)
        entry: dict[str, Any] = {
            "elapsed": elapsed,
            "tcp_connected": banner.get("connected", False),
            "banner_ok": banner.get("ok", False),
            "banner": banner.get("banner", ""),
            "banner_error": banner.get("error"),
        }
        last_banner = banner
        if banner.get("ok") or banner.get("connected"):
            ssh_probe = probe_ssh_command(
                ssh_key=ssh_key,
                host=host,
                port=port,
                timeout=max(DEFAULT_SSH_COMMAND_TIMEOUT, 10),
            )
            entry["ssh_ok"] = ssh_probe["ok"]
            entry["ssh_error"] = ssh_probe.get("error")
            entry["ssh_failure_class"] = ssh_probe.get("failure_class")
            last_ssh = ssh_probe
            timeline.append(entry)
            if ssh_probe["ok"]:
                return {
                    "ok": True,
                    "elapsed": round(time.monotonic() - start, 1),
                    "error": None,
                    "failure_class": None,
                    "timeline": timeline,
                    "banner": banner.get("banner", ""),
                    "ssh_probe": ssh_probe,
                }
        else:
            timeline.append(entry)
        time.sleep(poll_interval)

    console_excerpt = _read_console_excerpt(console_log)
    classified = classify_boot_failure(console_excerpt=console_excerpt, last_banner=last_banner, last_ssh=last_ssh)
    return {
        "ok": False,
        "elapsed": round(time.monotonic() - start, 1),
        "error": classified["reason"],
        "failure_class": classified["failure_class"],
        "timeline": timeline,
        "banner": last_banner.get("banner", "") if last_banner else "",
        "ssh_probe": last_ssh,
        "console_excerpt": console_excerpt,
        "boot_classification": classified,
    }


def boot_vm(
    kernel: pathlib.Path,
    disk_image: pathlib.Path,
    ssh_port: int = DEFAULT_SSH_PORT,
    mem_mb: int = DEFAULT_MEM_MB,
    console_log: pathlib.Path | None = None,
    boot_timeout: float = DEFAULT_BOOT_TIMEOUT,
    ssh_key: pathlib.Path | None = None,
    extra_append: str = "",
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
        extra_append=extra_append,
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

    if ssh_key is not None:
        ssh_result = wait_for_ssh_command(
            ssh_key=ssh_key,
            port=ssh_port,
            timeout=boot_timeout,
            console_log=console_log,
        )
    else:
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
        "-o", f"ConnectTimeout={DEFAULT_SSH_CONNECT_TIMEOUT}",
        "-o", "LogLevel=ERROR",
        "-i", str(ssh_key),
        "-p", str(port),
        "root@127.0.0.1",
    ]
