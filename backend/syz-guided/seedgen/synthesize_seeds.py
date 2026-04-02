#!/usr/bin/env python3
"""Synthesize runnable syzkaller .prog seeds from state_model_v1.json.

Seeds preserve the mandatory bootstrap prefix and the KVM resource chain.
Each seed is a text file in syzkaller's prog format.

Usage:
    python synthesize_seeds.py \
        --state-model path/to/state_model_v1.json \
        --out-dir path/to/seeds/
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Pack call → syz line mappings (v1: dry-run runnable text, not semantic synthesis)
# ---------------------------------------------------------------------------

_SYZ_CALL_MAPS: dict[str, dict[str, str]] = {
    "kvm": {
        "openat$KVM": 'r0 = openat$kvm(0xffffffffffffff9c, &AUTO="/dev/kvm\\x00", 0x2, 0x0)',
        "ioctl$KVM_CREATE_VM": "r1 = ioctl$KVM_CREATE_VM(r0, 0xae01, 0x0)",
        "ioctl$KVM_CREATE_VCPU": "r2 = ioctl$KVM_CREATE_VCPU(r1, 0xae41, 0x0)",
        "ioctl$KVM_ARM_VCPU_INIT": "ioctl$KVM_ARM_VCPU_INIT(r2, 0xae02, &AUTO={0x0, 0x0})",
        "ioctl$KVM_SET_ONE_REG": "ioctl$KVM_SET_ONE_REG(r2, 0xae04, &AUTO={0x6030000000100042, &AUTO=0x0})",
        "ioctl$KVM_GET_ONE_REG": "ioctl$KVM_GET_ONE_REG(r2, 0xae05, &AUTO={0x6030000000100042, &AUTO})",
        "ioctl$KVM_RUN": "ioctl$KVM_RUN(r2, 0xae80, 0x0)",
        "close$KVM": "close(r2)",
    },
    "io_uring": {
        "io_uring_setup": "r0 = io_uring_setup(0x8, &AUTO)",
        "io_uring_register": "io_uring_register(r0, 0x0, &AUTO, 0x0)",
        "io_uring_enter": "io_uring_enter(r0, 0x1, 0x0, 0x0, 0x0, 0x0)",
        "close": "close(r0)",
    },
    "net": {
        "socket$nl_netfilter": "r0 = socket$nl_netfilter(0x10, 0x3, 0xc)",
        "socket$nl_generic": "r0 = socket$nl_generic(0x10, 0x3, 0x10)",
        "socket$nl_route": "r0 = socket$nl_route(0x10, 0x3, 0x0)",
        "sendmsg$NFT_BATCH": "sendmsg$NFT_BATCH(r0, &AUTO, 0x0)",
        "sendmsg$NETLINK": "sendmsg$NETLINK(r0, &AUTO, 0x0)",
        "sendmsg": "sendmsg(r0, &AUTO, 0x0)",
        "recvmsg": "recvmsg(r0, &AUTO, 0x0)",
        "close": "close(r0)",
    },
    "bpf": {
        "bpf$MAP_CREATE": "r0 = bpf$MAP_CREATE(0x0, &AUTO)",
        "bpf$PROG_LOAD": "r1 = bpf$PROG_LOAD(0x0, &AUTO)",
        "bpf$PROG_ATTACH": "bpf$PROG_ATTACH(0x0, &AUTO)",
        "bpf$BPF_LINK_CREATE": "r2 = bpf$BPF_LINK_CREATE(0x0, &AUTO)",
        "bpf$MAP_UPDATE_ELEM": "bpf$MAP_UPDATE_ELEM(0x0, &AUTO)",
        "bpf$MAP_LOOKUP_ELEM": "bpf$MAP_LOOKUP_ELEM(0x0, &AUTO)",
        "bpf$PROG_DETACH": "bpf$PROG_DETACH(0x0, &AUTO)",
        "close": "close(r0)",
    },
    "fs": {
        "fsopen": "r0 = fsopen(&AUTO=\"ext4\\x00\", 0x0)",
        "fsconfig": "fsconfig(r0, 0x0, &AUTO, &AUTO, 0x0)",
        "fsmount": "r1 = fsmount(r0, 0x0, 0x0)",
        "move_mount": "move_mount(r1, 0x0, 0xffffffffffffff9c, &AUTO, 0x0)",
        "open_tree": "r2 = open_tree(0xffffffffffffff9c, &AUTO, 0x0)",
        "mount_setattr": "mount_setattr(r1, 0xffffffff, &AUTO, 0x0)",
        "umount2": "umount2(&AUTO, 0x0)",
        "openat$FUSE": "r0 = openat$FUSE(0xffffffffffffff9c, &AUTO=\"/dev/fuse\\x00\", 0x2, 0x0)",
        "close": "close(r0)",
    },
}

_KVM_SEED_VARIANTS = [
    {"name": "full_run", "suffix": ["ioctl$KVM_RUN"]},
    {"name": "run_close", "suffix": ["ioctl$KVM_RUN", "close$KVM"]},
    {"name": "double_run", "suffix": ["ioctl$KVM_RUN", "ioctl$KVM_RUN"]},
    {"name": "close_only", "suffix": ["close$KVM"]},
]


def _render_prog(
    calls: list[str],
    candidate_id: str,
    variant_name: str,
    immutable_prefix_len: int,
    call_map: dict[str, str],
) -> str:
    """Render a list of canonical call names into syzkaller prog text."""
    lines = [f"# candidate: {candidate_id}"]
    lines.append(f"# variant: {variant_name}")
    lines.append(f"# immutable_prefix: {immutable_prefix_len}")
    lines.append("")

    for call in calls:
        syz_line = call_map.get(call)
        if syz_line is None:
            raise ValueError(f"Unsupported call for seed synthesis: {call}")
        lines.append(syz_line)

    return "\n".join(lines) + "\n"

def _pick_call_map(state_model: dict) -> dict[str, str]:
    subsystem = state_model.get("subsystem", "kvm")
    if subsystem not in _SYZ_CALL_MAPS:
        raise ValueError(f"Unsupported subsystem for seed synthesis: {subsystem}")
    return _SYZ_CALL_MAPS[subsystem]


def _generic_seed_variants(state_model: dict, call_map: dict[str, str]) -> list[dict[str, Any]]:
    """Generate simple suffix permutations from trigger calls."""
    trigger = [c for c in state_model["phases"]["trigger"]["calls"] if c in call_map]
    suffix0 = trigger[:1] if trigger else []

    close_call = "close" if "close" in call_map else None
    umount_call = "umount2" if "umount2" in call_map else None

    variants: list[dict[str, Any]] = []
    variants.append({"name": "full", "suffix": suffix0})
    if suffix0:
        variants.append({"name": "double_trigger", "suffix": suffix0 + suffix0})
    if close_call:
        variants.append({"name": "close_only", "suffix": [close_call]})
        if suffix0:
            variants.append({"name": "trigger_close", "suffix": suffix0 + [close_call]})
    if umount_call and (not suffix0 or suffix0[0] != umount_call):
        variants.append({"name": "umount_only", "suffix": [umount_call]})

    # De-dup by (name, suffix).
    deduped = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for v in variants:
        key = (v["name"], tuple(v["suffix"]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(v)
    return deduped


def synthesize(state_model: dict) -> list[dict]:
    """Generate seed programs from state model. Returns list of {name, calls, prog_text}."""
    bootstrap = state_model["phases"]["bootstrap"]["calls"]
    configure = state_model["phases"]["configure"]["calls"]
    candidate_id = state_model["candidate_id"]
    call_map = _pick_call_map(state_model)
    immutable_prefix_len = int(state_model.get("immutable_prefix_len", len(bootstrap)))

    seeds = []
    subsystem = state_model.get("subsystem", "kvm")
    variants = _KVM_SEED_VARIANTS if subsystem == "kvm" else _generic_seed_variants(state_model, call_map)

    for variant in variants:
        calls = bootstrap + configure + variant["suffix"]
        prog_text = _render_prog(calls, candidate_id, variant["name"], immutable_prefix_len, call_map)
        seeds.append({
            "name": f"seed_{variant['name']}.prog",
            "calls": calls,
            "prog_text": prog_text,
        })

    return seeds


def emit_manifest(seeds: list[dict], state_model: dict) -> dict:
    """Produce a seed manifest for the orchestrator."""
    return {
        "candidate_id": state_model["candidate_id"],
        "schema_version": "seed_manifest/v1",
        "seed_count": len(seeds),
        "immutable_prefix_len": state_model["immutable_prefix_len"],
        "seeds": [
            {
                "name": s["name"],
                "call_count": len(s["calls"]),
            }
            for s in seeds
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthesize syzkaller seeds from state model")
    parser.add_argument("--state-model", required=True, help="Path to state_model_v1.json")
    parser.add_argument("--out-dir", required=True, help="Output directory for seeds")
    args = parser.parse_args()

    sm_path = pathlib.Path(args.state_model)
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(sm_path) as f:
        state_model = json.load(f)

    if state_model.get("schema_version") != "state_model/v1":
        print(f"ERROR: expected state_model/v1, got '{state_model.get('schema_version')}'", file=sys.stderr)
        return 1

    seeds = synthesize(state_model)
    manifest = emit_manifest(seeds, state_model)

    for seed in seeds:
        seed_path = out_dir / seed["name"]
        with open(seed_path, "w") as f:
            f.write(seed["prog_text"])

    manifest_path = out_dir / "seed_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"Synthesized {len(seeds)} seeds + manifest in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
