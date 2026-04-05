#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pack_registry import resolve_target_manifest
from runtime.net_lab import rank_net_files


def _load_json(path: pathlib.Path) -> dict:
    with open(path) as f:
        return json.load(f)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Rank net-relevant files deterministically for lab runs')
    parser.add_argument('--target-profile', required=True)
    parser.add_argument('--candidate', default=None)
    parser.add_argument('--source-frame-summary', default=None)
    parser.add_argument('--output', default='-')
    args = parser.parse_args(argv)

    target_profile = _load_json(pathlib.Path(args.target_profile))
    candidate = _load_json(pathlib.Path(args.candidate)) if args.candidate else None
    source_frame_summary = _load_json(pathlib.Path(args.source_frame_summary)) if args.source_frame_summary else None
    manifest = resolve_target_manifest(subsystem='net', target_family='net-netfilter-arm64-v1')
    report = rank_net_files(
        candidate=candidate,
        target_profile=target_profile,
        manifest=manifest,
        source_frame_summary=source_frame_summary,
    )
    text = json.dumps(report, indent=2, sort_keys=True) + '\n'
    if args.output == '-':
        sys.stdout.write(text)
    else:
        pathlib.Path(args.output).write_text(text, encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
