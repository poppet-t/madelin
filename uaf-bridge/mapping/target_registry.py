from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
TARGETS_ROOT = REPO_ROOT / "targets"


@lru_cache(maxsize=1)
def load_target_manifests() -> dict[str, dict[str, Any]]:
    manifests: dict[str, dict[str, Any]] = {}
    for manifest_path in sorted(TARGETS_ROOT.glob("*/manifest.json")):
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        pack = payload.get("pack")
        if isinstance(pack, str):
            manifests[pack] = payload
    return manifests


def target_manifest(pack: str) -> dict[str, Any]:
    manifests = load_target_manifests()
    if pack not in manifests:
        raise ValueError(f"unknown target pack: {pack}")
    return manifests[pack]


def ordered_target_manifests() -> list[dict[str, Any]]:
    return [load_target_manifests()[key] for key in sorted(load_target_manifests())]


def resolve_target_manifest(
    *,
    kernel_area: str | None = None,
    subsystem: str | None = None,
    target_family: str | None = None,
    default_pack: str = "kvm",
) -> dict[str, Any]:
    manifests = load_target_manifests()
    if isinstance(subsystem, str) and subsystem in manifests:
        return manifests[subsystem]
    if isinstance(target_family, str):
        for manifest in ordered_target_manifests():
            families = manifest.get("target_families", [])
            if isinstance(families, list) and target_family in families:
                return manifest
    if isinstance(kernel_area, str):
        for manifest in ordered_target_manifests():
            prefixes = manifest.get("kernel_area_prefixes", [])
            if isinstance(prefixes, list) and any(kernel_area.startswith(prefix) for prefix in prefixes if isinstance(prefix, str)):
                return manifest
    return target_manifest(default_pack)


def target_context(
    *,
    kernel_area: str | None = None,
    subsystem: str | None = None,
    target_family: str | None = None,
    arch: str | None = None,
    default_pack: str = "kvm",
) -> dict[str, str]:
    manifest = resolve_target_manifest(
        kernel_area=kernel_area,
        subsystem=subsystem,
        target_family=target_family,
        default_pack=default_pack,
    )
    families = manifest.get("target_families", [])
    resolved_family = target_family if isinstance(target_family, str) and target_family else (families[0] if isinstance(families, list) and families else f"{manifest['pack']}-arm64-v1")
    prefixes = manifest.get("kernel_area_prefixes", [])
    resolved_area = kernel_area if isinstance(kernel_area, str) and kernel_area else (prefixes[0] if isinstance(prefixes, list) and prefixes else "unknown")
    resolved_arch = arch if isinstance(arch, str) and arch else str(manifest.get("arch", "arm64"))
    return {
        "arch": resolved_arch,
        "kernel_area": resolved_area,
        "subsystem": str(manifest["subsystem"]),
        "target_family": str(resolved_family),
    }


def supported_entry_kinds(pack: str) -> set[str]:
    kinds = target_manifest(pack).get("supported_entry_kinds", [])
    return {str(kind) for kind in kinds if isinstance(kind, str)}
