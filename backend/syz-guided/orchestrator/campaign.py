#!/usr/bin/env python3
"""Bounded campaign orchestrator for candidate-directed fuzzing.

Manages the lifecycle of a single candidate realization campaign:
  1. Load runtime artifacts (state model, target profile, relation graph)
  2. Import seed corpus
  3. Run bounded fuzzing iterations
  4. Score and queue programs
  5. Invoke triage on crashes
  6. Emit campaign artifacts

Usage:
    python campaign.py \
        --artifacts-dir path/to/generated/ \
        --seeds-dir path/to/seeds/ \
        --work-dir path/to/workdir/ \
        --max-iterations 100
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from typing import Any

# Allow imports from parent package.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from orchestrator.score import score_program
from orchestrator.queue import FuzzQueue


def _load_json(path: pathlib.Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _write_json(data: dict, path: pathlib.Path) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


class Campaign:
    """A bounded candidate realization campaign."""

    def __init__(
        self,
        state_model: dict,
        target_profile: dict,
        relation_graph: dict,
        work_dir: pathlib.Path,
        max_iterations: int = 100,
    ):
        self.state_model = state_model
        self.target_profile = target_profile
        self.relation_graph = relation_graph
        self.work_dir = work_dir
        self.max_iterations = max_iterations
        self.queue = FuzzQueue()
        self.iteration = 0
        self.crashes: list[dict] = []
        self.stats: dict[str, Any] = {
            "candidate_id": state_model["candidate_id"],
            "iterations": 0,
            "programs_scored": 0,
            "crashes_found": 0,
            "best_score": 0.0,
            "start_time": None,
            "end_time": None,
        }

    def import_seeds(self, seeds_dir: pathlib.Path) -> int:
        """Import seed programs from a directory. Returns count imported."""
        count = 0
        for prog_file in sorted(seeds_dir.glob("*.prog")):
            calls = self._parse_prog(prog_file)
            if calls:
                scores = score_program(
                    calls, self.state_model, self.target_profile,
                )
                self.queue.add(calls, scores)
                count += 1
        return count

    def _parse_prog(self, path: pathlib.Path) -> list[str]:
        """Parse a .prog file into canonical call names."""
        calls = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Extract canonical call name from syz line.
                # Format: [rN = ]call_name(args...)
                parts = line.split("=", 1)
                call_part = parts[-1].strip()
                paren = call_part.find("(")
                if paren > 0:
                    call_name = call_part[:paren].strip()
                    # Normalize: syzkaller uses lowercase $kvm, our model uses $KVM
                    call_name = self._normalize_call(call_name)
                    calls.append(call_name)
        return calls

    @staticmethod
    def _normalize_call(call: str) -> str:
        """Normalize syzkaller call names to match state model conventions."""
        # Map openat$kvm → openat$KVM etc.
        replacements = {
            "openat$kvm": "openat$KVM",
        }
        return replacements.get(call, call)

    def run(self) -> dict:
        """Run the bounded campaign. Returns campaign summary."""
        self.stats["start_time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        for i in range(self.max_iterations):
            self.iteration = i + 1
            parent = self.queue.pick_parent()
            if parent is None:
                break

            # In v1 the actual syzkaller execution is stubbed.
            # The orchestrator skeleton demonstrates the full loop:
            #   1. pick parent
            #   2. mutate (in real run)
            #   3. execute (via syzkaller_runner)
            #   4. score result
            #   5. triage crashes
            #   6. update queue

            self.stats["programs_scored"] += 1
            best = max(-parent.priority, self.stats["best_score"])
            self.stats["best_score"] = best

            # Periodic promotion/demotion.
            if i % 10 == 0:
                self.queue.promote_demote()

        self.stats["iterations"] = self.iteration
        self.stats["end_time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.stats["queue"] = self.queue.stats()

        return self.stats

    def save_artifacts(self) -> None:
        """Save campaign artifacts to work_dir."""
        self.work_dir.mkdir(parents=True, exist_ok=True)
        _write_json(self.stats, self.work_dir / "campaign_summary.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded candidate campaign")
    parser.add_argument("--artifacts-dir", required=True, help="Directory with state model, target profile, relation graph")
    parser.add_argument("--seeds-dir", required=True, help="Directory with .prog seeds")
    parser.add_argument("--work-dir", required=True, help="Campaign work directory")
    parser.add_argument("--max-iterations", type=int, default=100, help="Maximum iterations")
    args = parser.parse_args()

    artifacts = pathlib.Path(args.artifacts_dir)
    sm = _load_json(artifacts / "state_model_v1.json")
    tp = _load_json(artifacts / "target_profile.json")
    rg = _load_json(artifacts / "relation_graph_v1.json")

    campaign = Campaign(
        state_model=sm,
        target_profile=tp,
        relation_graph=rg,
        work_dir=pathlib.Path(args.work_dir),
        max_iterations=args.max_iterations,
    )

    seed_count = campaign.import_seeds(pathlib.Path(args.seeds_dir))
    print(f"Imported {seed_count} seeds")

    summary = campaign.run()
    campaign.save_artifacts()

    print(f"Campaign complete: {summary['iterations']} iterations, {summary['programs_scored']} scored, best={summary['best_score']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
