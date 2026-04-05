#!/usr/bin/env python3

from __future__ import annotations

import pathlib
import sys
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from triage.io_uring_verdict import classify_io_uring_runtime_verdict


class TestIoUringVerdict(unittest.TestCase):
    def test_candidate_correlated_crash(self) -> None:
        verdict = classify_io_uring_runtime_verdict(
            execution_trace_summary={"timeouts": 0, "crashes_detected": 1, "seeds_executed": 2, "trigger_phase_reached": 1},
            candidate_alignment_report={"best_match_score": 0.9, "any_uaf_type_match": True},
            preserved_prefix_report={"prefix_valid_rate": 1.0},
            concurrency_window_report={"overlap_window_attempted": True},
        )
        self.assertEqual(verdict["verdict_class"], "candidate-correlated crash")

    def test_hang_or_timeout(self) -> None:
        verdict = classify_io_uring_runtime_verdict(
            execution_trace_summary={"timeouts": 2, "crashes_detected": 0, "seeds_executed": 2, "trigger_phase_reached": 0},
            candidate_alignment_report={"best_match_score": 0.0, "any_uaf_type_match": False},
            preserved_prefix_report={"prefix_valid_rate": 1.0},
            concurrency_window_report={"overlap_window_attempted": False},
        )
        self.assertEqual(verdict["verdict_class"], "hang/stall/timeout")

    def test_no_crash_but_target_path_exercised(self) -> None:
        verdict = classify_io_uring_runtime_verdict(
            execution_trace_summary={"timeouts": 0, "crashes_detected": 0, "seeds_executed": 3, "trigger_phase_reached": 2},
            candidate_alignment_report={"best_match_score": 0.1, "any_uaf_type_match": False},
            preserved_prefix_report={"prefix_valid_rate": 1.0},
            concurrency_window_report={"overlap_window_attempted": True},
        )
        self.assertEqual(verdict["verdict_class"], "no crash but target path exercised")

    def test_probable_unrelated_crash(self) -> None:
        verdict = classify_io_uring_runtime_verdict(
            execution_trace_summary={"timeouts": 0, "crashes_detected": 1, "seeds_executed": 2, "trigger_phase_reached": 1},
            candidate_alignment_report={"best_match_score": 0.1, "any_uaf_type_match": False},
            preserved_prefix_report={"prefix_valid_rate": 1.0},
            concurrency_window_report={"overlap_window_attempted": True},
        )
        self.assertEqual(verdict["verdict_class"], "probable unrelated crash")

    def test_unsupported_insufficient_evidence(self) -> None:
        verdict = classify_io_uring_runtime_verdict(
            execution_trace_summary={"timeouts": 0, "crashes_detected": 0, "seeds_executed": 0, "trigger_phase_reached": 0},
            candidate_alignment_report={"best_match_score": 0.0, "any_uaf_type_match": False},
            preserved_prefix_report={"prefix_valid_rate": 0.0},
            concurrency_window_report={"overlap_window_attempted": False},
        )
        self.assertEqual(verdict["verdict_class"], "unsupported/insufficient evidence")

    def test_no_meaningful_target_path_exercise(self) -> None:
        verdict = classify_io_uring_runtime_verdict(
            execution_trace_summary={"timeouts": 0, "crashes_detected": 0, "seeds_executed": 3, "trigger_phase_reached": 1},
            candidate_alignment_report={"best_match_score": 0.0, "any_uaf_type_match": False},
            preserved_prefix_report={"prefix_valid_rate": 0.5},
            concurrency_window_report={"overlap_window_attempted": False},
        )
        self.assertEqual(verdict["verdict_class"], "no meaningful target-path exercise")

    def test_no_meaningful_target_path_no_trigger(self) -> None:
        verdict = classify_io_uring_runtime_verdict(
            execution_trace_summary={"timeouts": 0, "crashes_detected": 0, "seeds_executed": 3, "trigger_phase_reached": 0},
            candidate_alignment_report={"best_match_score": 0.0, "any_uaf_type_match": False},
            preserved_prefix_report={"prefix_valid_rate": 1.0},
            concurrency_window_report={"overlap_window_attempted": False},
        )
        self.assertEqual(verdict["verdict_class"], "no meaningful target-path exercise")

    def test_verdict_includes_signals(self) -> None:
        verdict = classify_io_uring_runtime_verdict(
            execution_trace_summary={"timeouts": 1, "crashes_detected": 0, "seeds_executed": 2, "trigger_phase_reached": 0},
            candidate_alignment_report={"best_match_score": 0.0, "any_uaf_type_match": False},
            preserved_prefix_report={"prefix_valid_rate": 1.0},
            concurrency_window_report={"overlap_window_attempted": False},
        )
        self.assertIn("signals", verdict)
        self.assertEqual(verdict["signals"]["timeouts"], 1)
        self.assertEqual(verdict["signals"]["seeds_executed"], 2)

    def test_verdict_includes_reasons(self) -> None:
        verdict = classify_io_uring_runtime_verdict(
            execution_trace_summary={"timeouts": 0, "crashes_detected": 1, "seeds_executed": 2, "trigger_phase_reached": 1},
            candidate_alignment_report={"best_match_score": 0.9, "any_uaf_type_match": True},
            preserved_prefix_report={"prefix_valid_rate": 1.0},
            concurrency_window_report={"overlap_window_attempted": True},
        )
        self.assertIn("reasons", verdict)
        self.assertGreater(len(verdict["reasons"]), 0)


if __name__ == "__main__":
    unittest.main()
