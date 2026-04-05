#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from runtime.net_lab import rank_net_seeds


def _load_json(path: pathlib.Path) -> dict:
    with open(path) as f:
        return json.load(f)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Rank net seeds deterministically for lab runs')
    parser.add_argument('--seed-manifest', required=True)
    parser.add_argument('--target-profile', required=True)
    parser.add_argument('--candidate', default=None)
    parser.add_argument('--proof-mode', default='off')
    parser.add_argument('--output', default='-')
    args = parser.parse_args(argv)

    seed_manifest = _load_json(pathlib.Path(args.seed_manifest))
    target_profile = _load_json(pathlib.Path(args.target_profile))
    candidate = _load_json(pathlib.Path(args.candidate)) if args.candidate else None
    report = rank_net_seeds(
        seed_manifest=seed_manifest,
        target_profile=target_profile,
        candidate=candidate,
        proof_mode=args.proof_mode,
    )
    text = json.dumps(report, indent=2, sort_keys=True) + '\n'
    if args.output == '-':
        sys.stdout.write(text)
    else:
        pathlib.Path(args.output).write_text(text, encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
