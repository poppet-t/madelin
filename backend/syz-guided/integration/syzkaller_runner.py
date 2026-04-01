"""Syzkaller runner integration — manages syzkaller process lifecycle.

In v1 this is a thin wrapper that:
  1. Generates a syz-manager config from campaign parameters
  2. Launches syz-manager with the seed corpus
  3. Monitors for crashes
  4. Collects coverage metadata
  5. Stops after the campaign budget expires

Real syzkaller execution requires:
  - syz-manager binary
  - kernel image
  - disk image
  - SSH key
  - arm64 QEMU/KVM setup

This module provides the interface; actual execution depends on environment.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
from typing import Any


def generate_syz_config(
    state_model: dict,
    seeds_dir: pathlib.Path,
    work_dir: pathlib.Path,
    kernel_image: pathlib.Path | None = None,
    disk_image: pathlib.Path | None = None,
    ssh_key: pathlib.Path | None = None,
    syz_dir: pathlib.Path | None = None,
    max_duration_seconds: int = 600,
) -> dict:
    """Generate a syz-manager configuration for a candidate campaign.

    Returns a config dict suitable for writing to syz-manager.cfg.
    """
    config = {
        "name": f"campaign_{state_model['candidate_id']}",
        "target": "linux/arm64",
        "http": "localhost:0",
        "workdir": str(work_dir / "syz-workdir"),
        "reproduce": True,
        "cover": True,
        "procs": 2,
        "type": "qemu",
        "vm": {
            "count": 1,
            "cpu": 2,
            "mem": 2048,
        },
    }

    if kernel_image:
        config["kernel_obj"] = str(kernel_image.parent)
        config["vm"]["kernel"] = str(kernel_image)
    if disk_image:
        config["image"] = str(disk_image)
    if ssh_key:
        config["sshkey"] = str(ssh_key)
    if syz_dir:
        config["syzkaller"] = str(syz_dir)

    # Seed corpus injection.
    config["_madelin_seeds_dir"] = str(seeds_dir)
    config["_madelin_candidate_id"] = state_model["candidate_id"]
    config["_madelin_max_duration"] = max_duration_seconds

    return config


def write_syz_config(config: dict, path: pathlib.Path) -> None:
    """Write config as JSON for syz-manager."""
    with open(path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


def check_syz_available(syz_dir: pathlib.Path) -> dict:
    """Check if syzkaller binaries are available."""
    results = {}
    for binary in ["syz-manager", "syz-executor", "syz-execprog"]:
        path = syz_dir / "linux_arm64" / binary
        results[binary] = path.exists()
    return results
