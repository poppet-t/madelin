#!/usr/bin/env python3
"""Synthesize runnable syzkaller .prog seeds from state_model_v1.json."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pack_registry import resolve_target_manifest


def _render_prog(
    calls: list[str],
    candidate_id: str,
    variant_name: str,
    immutable_prefix_len: int,
    call_map: dict[str, str],
) -> str:
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


def _manifest_for_state_model(state_model: dict) -> dict:
    return resolve_target_manifest(
        subsystem=state_model.get("subsystem") if isinstance(state_model.get("subsystem"), str) else None,
        target_family=state_model.get("target_family") if isinstance(state_model.get("target_family"), str) else None,
    )


def _seed_variants(state_model: dict, manifest: dict) -> list[dict]:
    variants = manifest.get("seed_variants", [])
    if not isinstance(variants, list) or not variants:
        trigger_calls = state_model.get("phases", {}).get("trigger", {}).get("calls", [])
        return [{"name": "full", "suffix": [str(call) for call in trigger_calls if isinstance(call, str)]}]
    return [variant for variant in variants if isinstance(variant, dict)]


def synthesize(state_model: dict) -> list[dict]:
    bootstrap = state_model["phases"]["bootstrap"]["calls"]
    configure = state_model["phases"]["configure"]["calls"]
    candidate_id = state_model["candidate_id"]
    immutable_prefix_len = int(state_model.get("immutable_prefix_len", len(bootstrap)))
    manifest = _manifest_for_state_model(state_model)
    call_map = {str(key): str(value) for key, value in manifest.get("syz_call_map", {}).items() if isinstance(key, str)}
    variants = _seed_variants(state_model, manifest)

    seeds = []
    for variant in variants:
        suffix = [str(call) for call in variant.get("suffix", []) if isinstance(call, str)]
        calls = list(bootstrap) + list(configure) + suffix
        prog_text = _render_prog(calls, candidate_id, str(variant.get("name", "variant")), immutable_prefix_len, call_map)
        seeds.append({
            "name": f"seed_{variant.get('name', 'variant')}.prog",
            "calls": calls,
            "prog_text": prog_text,
        })

    return seeds


def emit_manifest(seeds: list[dict], state_model: dict) -> dict:
    return {
        "candidate_id": state_model["candidate_id"],
        "schema_version": "seed_manifest/v1",
        "seed_count": len(seeds),
        "immutable_prefix_len": state_model["immutable_prefix_len"],
        "seeds": [
            {
                "name": seed["name"],
                "call_count": len(seed["calls"]),
            }
            for seed in seeds
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
