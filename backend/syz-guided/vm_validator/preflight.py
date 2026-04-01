"""Preflight checks for vm_validator one-shot runs.

Validates that all host-side prerequisites exist before attempting a QEMU boot.
Returns structured results so callers can decide whether to proceed or report.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
from typing import Any


def check_qemu() -> dict:
    """Check that qemu-system-aarch64 is available."""
    path = shutil.which("qemu-system-aarch64")
    if path is None:
        return {"ok": False, "name": "qemu", "error": "qemu-system-aarch64 not found in PATH"}
    # Probe version.
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True, text=True, timeout=5,
        )
        version_line = result.stdout.strip().split("\n")[0] if result.stdout else "unknown"
    except (subprocess.TimeoutExpired, OSError):
        version_line = "unknown"
    return {"ok": True, "name": "qemu", "path": path, "version": version_line}


def check_file(path: pathlib.Path, label: str) -> dict:
    """Check that a required file exists and is non-empty."""
    if not path.exists():
        return {"ok": False, "name": label, "error": f"{label} not found: {path}"}
    if not path.is_file():
        return {"ok": False, "name": label, "error": f"{label} is not a regular file: {path}"}
    if path.stat().st_size == 0:
        return {"ok": False, "name": label, "error": f"{label} is empty: {path}"}
    return {"ok": True, "name": label, "path": str(path), "size_bytes": path.stat().st_size}


def check_ssh_key(path: pathlib.Path) -> dict:
    """Check SSH private key exists and has restricted permissions."""
    base = check_file(path, "ssh_key")
    if not base["ok"]:
        return base
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        return {
            "ok": False,
            "name": "ssh_key",
            "error": f"SSH key {path} has too-open permissions: {oct(mode)}. Run: chmod 600 {path}",
        }
    return base


def run_preflight(
    kernel: pathlib.Path,
    disk_image: pathlib.Path,
    ssh_key: pathlib.Path,
    syz_execprog: pathlib.Path | None = None,
) -> dict:
    """Run all preflight checks. Returns structured summary.

    The result dict has:
      - checks: list of individual check results
      - ready: bool — True only if all required checks pass
      - warnings: list of non-fatal notes
    """
    checks: list[dict] = []
    warnings: list[str] = []

    checks.append(check_qemu())
    checks.append(check_file(kernel, "kernel"))
    checks.append(check_file(disk_image, "disk_image"))
    checks.append(check_ssh_key(ssh_key))

    if syz_execprog is not None:
        checks.append(check_file(syz_execprog, "syz_execprog"))
    else:
        warnings.append("syz_execprog not provided — prog injection will be skipped")

    failed = [c for c in checks if not c["ok"]]
    return {
        "ready": len(failed) == 0,
        "checks": checks,
        "warnings": warnings,
        "failed_count": len(failed),
    }
