#!/usr/bin/env python3
"""Tests for triage module."""

import json
import pathlib
import sys
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from state_model.build_state_model import build_state_model, build_target_profile
from triage.parse_kasan import parse_kasan_report
from triage.match_candidate import match_crash
from triage.report import build_triage_report
from schemas import validate

_FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

# Synthetic KASAN report matching the KVM timer candidate.
_KASAN_UAF_REPORT = """
BUG: KASAN: use-after-free in kvm_timer_should_fire+0x1a/0x30 arch/arm64/kvm/arch_timer.c:923
Read of size 8 at addr ffff0000deadbeef by task syz-executor/1234

Call Trace:
 kvm_timer_should_fire+0x1a/0x30
 kvm_vcpu_check_block+0x4e/0x90
 kvm_arch_vcpu_ioctl_run+0x123/0x456

Allocated by task 1233:
 kvm_timer_vcpu_init+0x12/0x34

Freed by task 1232:
 kvm_timer_vcpu_terminate+0x56/0x78
 kvm_arch_destroy_vm+0xab/0xcd
"""

_KASAN_UNRELATED_REPORT = """
BUG: KASAN: slab-out-of-bounds in some_other_function+0x10/0x20 net/core/sock.c:100
Read of size 4 at addr ffff0000cafebabe by task syz-executor/5678

Call Trace:
 some_other_function+0x10/0x20
 sock_sendmsg+0x30/0x40
"""


def _load(name: str) -> dict:
    with open(_FIXTURES / name) as f:
        return json.load(f)


class TestParseKasan(unittest.TestCase):
    def test_parse_uaf_report(self):
        result = parse_kasan_report(_KASAN_UAF_REPORT)
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "use-after-free")
        self.assertIn("kvm_timer_should_fire", result["stack_frames"])
        self.assertIn("kvm_timer_vcpu_terminate", result["stack_frames"])

    def test_parse_unrelated_report(self):
        result = parse_kasan_report(_KASAN_UNRELATED_REPORT)
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "slab-out-of-bounds")
        self.assertNotIn("kvm_timer_should_fire", result["stack_frames"])

    def test_no_kasan_returns_none(self):
        result = parse_kasan_report("normal kernel output\nno bugs here\n")
        self.assertIsNone(result)


class TestMatchCandidate(unittest.TestCase):
    def setUp(self):
        candidate = _load("candidate.json")
        self.tp = build_target_profile(candidate)

    def test_matching_crash_scores_high(self):
        crash = parse_kasan_report(_KASAN_UAF_REPORT)
        match = match_crash(crash, self.tp)
        self.assertTrue(match["uaf_type_match"])
        self.assertTrue(match["focus_frame_hit"])
        self.assertTrue(match["free_use_hint_match"])
        self.assertGreater(match["match_score"], 0.7)

    def test_unrelated_crash_scores_low(self):
        crash = parse_kasan_report(_KASAN_UNRELATED_REPORT)
        match = match_crash(crash, self.tp)
        self.assertFalse(match["uaf_type_match"])
        self.assertFalse(match["focus_frame_hit"])
        self.assertAlmostEqual(match["match_score"], 0.0)


class TestTriageReport(unittest.TestCase):
    def setUp(self):
        candidate = _load("candidate.json")
        plan = _load("witness_plan.json")
        self.sm = build_state_model(
            candidate, plan, "fixtures/candidate.json", "fixtures/witness_plan.json",
        )
        self.tp = build_target_profile(candidate)

    def test_matching_crash_confirmed(self):
        calls = (
            self.sm["phases"]["bootstrap"]["calls"]
            + self.sm["phases"]["configure"]["calls"]
            + self.sm["phases"]["trigger"]["calls"]
        )
        report = build_triage_report(_KASAN_UAF_REPORT, self.tp, self.sm, calls)
        errors = validate(report, "triage_report_v1")
        self.assertEqual(errors, [], f"Schema errors: {errors}")
        self.assertEqual(report["verdict"], "confirmed")

    def test_unrelated_crash_unrelated(self):
        report = build_triage_report(_KASAN_UNRELATED_REPORT, self.tp, self.sm)
        errors = validate(report, "triage_report_v1")
        self.assertEqual(errors, [], f"Schema errors: {errors}")
        self.assertEqual(report["verdict"], "unrelated")

    def test_no_kasan_insufficient(self):
        report = build_triage_report("no kasan here", self.tp, self.sm)
        errors = validate(report, "triage_report_v1")
        self.assertEqual(errors, [], f"Schema errors: {errors}")
        self.assertEqual(report["verdict"], "insufficient_data")


if __name__ == "__main__":
    unittest.main()
