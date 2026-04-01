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
# KVM arm64 call → syz line mapping (v1 narrow slice)
# ---------------------------------------------------------------------------

_SYZ_CALL_MAP: dict[str, str] = {
    "openat$KVM": 'r0 = openat$kvm(0xffffffffffffff9c, &AUTO="/dev/kvm\\x00", 0x2, 0x0)',
    "ioctl$KVM_CREATE_VM": "r1 = ioctl$KVM_CREATE_VM(r0, 0xae01, 0x0)",
    "ioctl$KVM_CREATE_VCPU": "r2 = ioctl$KVM_CREATE_VCPU(r1, 0xae41, 0x0)",
    "ioctl$KVM_ARM_VCPU_INIT": "ioctl$KVM_ARM_VCPU_INIT(r2, 0xae02, &AUTO={0x0, 0x0})",
    "ioctl$KVM_SET_ONE_REG": "ioctl$KVM_SET_ONE_REG(r2, 0xae04, &AUTO={0x6030000000100042, &AUTO=0x0})",
    "ioctl$KVM_GET_ONE_REG": "ioctl$KVM_GET_ONE_REG(r2, 0xae05, &AUTO={0x6030000000100042, &AUTO})",
    "ioctl$KVM_RUN": "ioctl$KVM_RUN(r2, 0xae80, 0x0)",
    "close$KVM": "close(r2)",
}

# v1 seed variants — each is a different suffix permutation after the prefix.
_SEED_VARIANTS = [
    # Variant 0: full run — bootstrap + configure + run
    {
        "name": "full_run",
        "suffix": ["ioctl$KVM_RUN"],
    },
    # Variant 1: run + close — trigger teardown race
    {
        "name": "run_close",
        "suffix": ["ioctl$KVM_RUN", "close$KVM"],
    },
    # Variant 2: double run — stress timer path
    {
        "name": "double_run",
        "suffix": ["ioctl$KVM_RUN", "ioctl$KVM_RUN"],
    },
    # Variant 3: close only — immediate teardown
    {
        "name": "close_only",
        "suffix": ["close$KVM"],
    },
]


def _render_prog(calls: list[str], candidate_id: str, variant_name: str) -> str:
    """Render a list of canonical call names into syzkaller prog text."""
    lines = [f"# candidate: {candidate_id}"]
    lines.append(f"# variant: {variant_name}")
    lines.append(f"# immutable_prefix: {_count_prefix(calls)}")
    lines.append("")

    for call in calls:
        syz_line = _SYZ_CALL_MAP.get(call)
        if syz_line is None:
            lines.append(f"# UNSUPPORTED: {call}")
        else:
            lines.append(syz_line)

    return "\n".join(lines) + "\n"


def _count_prefix(calls: list[str]) -> int:
    """Count bootstrap prefix calls."""
    prefix_calls = {"openat$KVM", "ioctl$KVM_CREATE_VM", "ioctl$KVM_CREATE_VCPU"}
    count = 0
    for c in calls:
        if c in prefix_calls:
            count += 1
        else:
            break
    return count


def synthesize(state_model: dict) -> list[dict]:
    """Generate seed programs from state model. Returns list of {name, calls, prog_text}."""
    bootstrap = state_model["phases"]["bootstrap"]["calls"]
    configure = state_model["phases"]["configure"]["calls"]
    candidate_id = state_model["candidate_id"]

    seeds = []
    for variant in _SEED_VARIANTS:
        calls = bootstrap + configure + variant["suffix"]
        prog_text = _render_prog(calls, candidate_id, variant["name"])
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
