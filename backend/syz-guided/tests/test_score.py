#!/usr/bin/env python3
"""Tests for scoring module."""

import json
import pathlib
import sys
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from state_model.build_state_model import build_state_model, build_target_profile
from orchestrator.score import score_program

_FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> dict:
    with open(_FIXTURES / name) as f:
        return json.load(f)


class TestScoring(unittest.TestCase):
    def setUp(self):
        candidate = _load("candidate.json")
        plan = _load("witness_plan.json")
        self.sm = build_state_model(
            candidate, plan, "fixtures/candidate.json", "fixtures/witness_plan.json",
        )
        self.tp = build_target_profile(candidate)

    def test_full_program_scores_high(self):
        calls = (
            self.sm["phases"]["bootstrap"]["calls"]
            + self.sm["phases"]["configure"]["calls"]
            + self.sm["phases"]["trigger"]["calls"]
        )
        scores = score_program(calls, self.sm, self.tp)
        self.assertGreater(scores["total"], 0.5)
        self.assertEqual(scores["prefix_valid"], 1.0)
        self.assertEqual(scores["phase_progress"], 1.0)

    def test_empty_program_scores_near_zero(self):
        scores = score_program([], self.sm, self.tp)
        self.assertLess(scores["total"], 0.1)
        self.assertEqual(scores["prefix_valid"], 0.0)

    def test_bootstrap_only_scores_partial(self):
        calls = self.sm["phases"]["bootstrap"]["calls"]
        scores = score_program(calls, self.sm, self.tp)
        self.assertEqual(scores["prefix_valid"], 1.0)
        self.assertAlmostEqual(scores["phase_progress"], 0.33)

    def test_broken_prefix_scores_low(self):
        calls = ["WRONG_CALL"] + self.sm["phases"]["bootstrap"]["calls"][1:]
        scores = score_program(calls, self.sm, self.tp)
        self.assertEqual(scores["prefix_valid"], 0.0)

    def test_target_signal_with_crash_frames(self):
        calls = (
            self.sm["phases"]["bootstrap"]["calls"]
            + self.sm["phases"]["configure"]["calls"]
            + self.sm["phases"]["trigger"]["calls"]
        )
        signals = {
            "crash_frames": ["kvm_timer_vcpu_terminate"],
            "covered_files": ["arch/arm64/kvm/arch_timer.c"],
        }
        scores = score_program(calls, self.sm, self.tp, signals)
        self.assertGreater(scores["target_signal"], 0.0)

    def test_scores_all_between_0_and_1(self):
        calls = self.sm["phases"]["bootstrap"]["calls"]
        scores = score_program(calls, self.sm, self.tp)
        for key, val in scores.items():
            self.assertGreaterEqual(val, 0.0, f"{key} < 0")
            self.assertLessEqual(val, 1.0, f"{key} > 1")


if __name__ == "__main__":
    unittest.main()
