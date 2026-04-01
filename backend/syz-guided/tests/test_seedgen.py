#!/usr/bin/env python3
"""Tests for seed synthesis."""

import json
import pathlib
import sys
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from state_model.build_state_model import build_state_model
from seedgen.synthesize_seeds import synthesize, emit_manifest

_FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> dict:
    with open(_FIXTURES / name) as f:
        return json.load(f)


class TestSynthesizeSeeds(unittest.TestCase):
    def setUp(self):
        candidate = _load("candidate.json")
        plan = _load("witness_plan.json")
        self.sm = build_state_model(
            candidate, plan, "fixtures/candidate.json", "fixtures/witness_plan.json",
        )
        self.seeds = synthesize(self.sm)

    def test_produces_seeds(self):
        self.assertGreater(len(self.seeds), 0)

    def test_seeds_have_prog_text(self):
        for seed in self.seeds:
            self.assertIn("prog_text", seed)
            self.assertGreater(len(seed["prog_text"]), 0)

    def test_seeds_preserve_prefix(self):
        """Every seed must start with the bootstrap prefix calls."""
        bootstrap = self.sm["phases"]["bootstrap"]["calls"]
        for seed in self.seeds:
            for i, expected in enumerate(bootstrap):
                self.assertEqual(
                    seed["calls"][i], expected,
                    f"Seed {seed['name']} prefix mismatch at index {i}",
                )

    def test_seeds_include_configure(self):
        """Every seed must include configure calls after bootstrap."""
        configure = self.sm["phases"]["configure"]["calls"]
        prefix_len = self.sm["immutable_prefix_len"]
        for seed in self.seeds:
            for i, expected in enumerate(configure):
                self.assertEqual(
                    seed["calls"][prefix_len + i], expected,
                    f"Seed {seed['name']} configure mismatch at index {prefix_len + i}",
                )

    def test_prog_text_parseable(self):
        """Each seed prog_text has non-comment lines that look like syz calls."""
        for seed in self.seeds:
            lines = [l for l in seed["prog_text"].splitlines()
                     if l.strip() and not l.startswith("#")]
            self.assertGreater(len(lines), 0, f"Seed {seed['name']} has no call lines")

    def test_no_unsupported_calls(self):
        """No seed should contain UNSUPPORTED markers."""
        for seed in self.seeds:
            self.assertNotIn("UNSUPPORTED", seed["prog_text"],
                           f"Seed {seed['name']} has unsupported calls")


class TestSeedManifest(unittest.TestCase):
    def setUp(self):
        candidate = _load("candidate.json")
        plan = _load("witness_plan.json")
        self.sm = build_state_model(
            candidate, plan, "fixtures/candidate.json", "fixtures/witness_plan.json",
        )
        self.seeds = synthesize(self.sm)
        self.manifest = emit_manifest(self.seeds, self.sm)

    def test_manifest_candidate_id(self):
        self.assertEqual(self.manifest["candidate_id"], self.sm["candidate_id"])

    def test_manifest_seed_count(self):
        self.assertEqual(self.manifest["seed_count"], len(self.seeds))

    def test_manifest_prefix_len(self):
        self.assertEqual(
            self.manifest["immutable_prefix_len"],
            self.sm["immutable_prefix_len"],
        )


if __name__ == "__main__":
    unittest.main()
