#!/usr/bin/env python3
"""Tests for relation guard and prefix-safe mutator."""

import json
import pathlib
import random
import sys
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from state_model.build_state_model import build_state_model
from mutator.relation_guard import is_valid_mutation, check_prefix_intact, check_resource_chain
from mutator.prefix_safe_mutator import mutate

_FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> dict:
    with open(_FIXTURES / name) as f:
        return json.load(f)


class TestRelationGuard(unittest.TestCase):
    def setUp(self):
        candidate = _load("candidate.json")
        plan = _load("witness_plan.json")
        self.sm = build_state_model(
            candidate, plan, "fixtures/candidate.json", "fixtures/witness_plan.json",
        )
        self.valid_calls = (
            self.sm["phases"]["bootstrap"]["calls"]
            + self.sm["phases"]["configure"]["calls"]
            + self.sm["phases"]["trigger"]["calls"]
        )

    def test_valid_program_passes(self):
        valid, violations = is_valid_mutation(self.valid_calls, self.sm)
        self.assertTrue(valid, f"Violations: {violations}")

    def test_broken_prefix_fails(self):
        broken = ["WRONG"] + self.valid_calls[1:]
        valid, violations = is_valid_mutation(broken, self.sm)
        self.assertFalse(valid)
        self.assertTrue(any("prefix" in v.lower() for v in violations))

    def test_missing_producer_fails(self):
        # Remove openat$KVM (producer of fd_kvm).
        broken = self.valid_calls[1:]
        valid, violations = is_valid_mutation(broken, self.sm)
        self.assertFalse(valid)

    def test_resource_chain_valid(self):
        violations = check_resource_chain(self.valid_calls, self.sm)
        self.assertEqual(violations, [])


class TestPrefixSafeMutator(unittest.TestCase):
    def setUp(self):
        candidate = _load("candidate.json")
        plan = _load("witness_plan.json")
        self.sm = build_state_model(
            candidate, plan, "fixtures/candidate.json", "fixtures/witness_plan.json",
        )
        self.base_calls = (
            self.sm["phases"]["bootstrap"]["calls"]
            + self.sm["phases"]["configure"]["calls"]
            + self.sm["phases"]["trigger"]["calls"]
        )

    def test_mutation_preserves_prefix(self):
        """Mutated programs must always keep the bootstrap prefix."""
        rng = random.Random(42)
        prefix = self.sm["phases"]["bootstrap"]["calls"]
        for _ in range(50):
            mutated = mutate(self.base_calls, self.sm, rng)
            self.assertTrue(
                check_prefix_intact(mutated, self.sm),
                f"Prefix broken: {mutated[:len(prefix)]} != {prefix}",
            )

    def test_mutation_preserves_sticky_calls(self):
        """Sticky calls must survive mutation."""
        rng = random.Random(42)
        sticky = set(self.sm["sticky_calls"])
        for _ in range(50):
            mutated = mutate(self.base_calls, self.sm, rng)
            mutated_set = set(mutated)
            for s in sticky:
                self.assertIn(s, mutated_set, f"Sticky call '{s}' lost after mutation")

    def test_mutations_produce_variety(self):
        """Multiple mutations should not all be identical."""
        rng = random.Random(42)
        results = set()
        for _ in range(20):
            mutated = mutate(self.base_calls, self.sm, rng)
            results.add(tuple(mutated))
        self.assertGreater(len(results), 1, "All mutations identical — no variety")


if __name__ == "__main__":
    unittest.main()
