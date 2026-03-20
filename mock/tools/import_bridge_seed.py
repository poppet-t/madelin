#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bridge_seed.importer import import_bridge_seed


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import uaf-bridge mock_seed.json into MOCK seed corpus + bias artifacts")
    parser.add_argument("seed", help="Path to bridge-generated mock_seed.json")
    parser.add_argument(
        "--output-dir",
        default="seed_workdir",
        help="Directory where input programs, relation bias, and previews will be written",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print imported seed summary JSON to stdout")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    preview = import_bridge_seed(args.seed, args.output_dir)
    if args.dry_run:
        print(json.dumps(preview, indent=2, sort_keys=True))
    else:
        print(f"Imported bridge seed into: {Path(args.output_dir).resolve()}")
        print(json.dumps(preview, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
