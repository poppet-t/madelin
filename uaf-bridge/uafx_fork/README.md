# UAFX fork integration notes (narrow KVM/arm64 export slice)

This directory is a bridge-side staging area for the **UAFX fork patch plan**.

A local UAFX repository was not found automatically during implementation, so the exporter code here is written as a **drop-in post-processor / integration stub** that can be copied into a UAFX fork with minimal changes.

## Intended placement in a real UAFX fork

Recommended options:
- `tools/export_bridge_candidate.py`
- or `scripts/export_bridge_json.py`
- or as a post-processing wrapper around the existing warning JSON emitter

## Narrow scope implemented here

- one warning at a time
- `arch/arm64/kvm`
- one plausible ioctl-driven KVM candidate family
- stable richer export schema for bridge ingestion

## Suggested UAFX hook point

Best hook point in a real fork:
1. after the existing warning record has already been serialized into JSON-like data
2. before final output is written to disk
3. or as a post-processing script that reads one raw warning JSON record and writes one richer bridge export JSON record

That keeps the first integration low-risk and avoids redesigning the static pipeline.

## TODO when wiring to a real UAFX fork

- Replace the sample raw warning adapter with the actual UAFX warning shape.
- Fill `efp_summary`, `lock_summary`, `condition_summary`, and `thread_summary` from grounded UAFX analysis data when available.
- Keep emitting empty arrays when a summary is not available yet; do not invent facts.
