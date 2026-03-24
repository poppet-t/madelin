from __future__ import annotations

import unittest

from verdict.match_candidate import match_candidate
from verdict.parse_crash import parse_crash_text

MATCHING_UAF_LOG = """BUG: KASAN: use-after-free in kvm_timer_should_fire+0x20/0x70 arch/arm64/kvm/arch_timer.c:923
Read of size 8 at addr 0xffff000012340000 by task syz-executor/1234

Call trace:
 dump_stack_lvl+0x1a0/0x1f0 lib/dump_stack.c:120
 kvm_timer_should_fire+0x20/0x70 arch/arm64/kvm/arch_timer.c:923
 kvm_timer_flush_hwstate+0x88/0xe0 arch/arm64/kvm/arch_timer.c:1024
 kvm_vcpu_ioctl+0x120/0x2b0 arch/arm64/kvm/arm.c:342

Freed by task 1234:
 kasan_save_stack+0x30/0x60 mm/kasan/common.c:45
 kvm_timer_vcpu_terminate+0x94/0x1b0 arch/arm64/kvm/arch_timer.c:812
 kvm_vcpu_release+0x40/0x80 virt/kvm/kvm_main.c:123
"""

SLAB_OOB_LOG = """BUG: KASAN: slab-out-of-bounds in unrelated_driver_ioctl+0x10/0x40 drivers/net/unrelated.c:55
Write of size 16 at addr 0xffff000043210000 by task syz-executor/77

Call trace:
 unrelated_driver_ioctl+0x10/0x40 drivers/net/unrelated.c:55
 vfs_ioctl+0x44/0x90 fs/ioctl.c:51
"""


CANDIDATE = {
    "candidate_id": "cand_demo",
    "analysis_context": {"kernel_area": "arch/arm64/kvm"},
    "loc0": {
        "function": "kvm_timer_vcpu_terminate",
        "file": "arch/arm64/kvm/arch_timer.c",
        "line": 812,
    },
    "loc1": {
        "function": "kvm_timer_should_fire",
        "file": "arch/arm64/kvm/arch_timer.c",
        "line": 923,
    },
    "entries": [{"entry_func": "kvm_vcpu_ioctl"}],
}


class CrashMatcherTests(unittest.TestCase):
    def test_matching_uaf_confirms_candidate(self) -> None:
        result = match_candidate(parse_crash_text(MATCHING_UAF_LOG), CANDIDATE, {"seeded_run_completed": True})

        self.assertEqual(result["verdict"], "CONFIRMED")
        self.assertEqual(result["confidence"], "high")
        self.assertTrue(result["evidence"]["loc0_match"])
        self.assertTrue(result["evidence"]["loc1_match"])
        self.assertTrue(result["evidence"]["crash_type_match"])

    def test_unrelated_crash_is_reported(self) -> None:
        result = match_candidate(parse_crash_text(SLAB_OOB_LOG), CANDIDATE, {"seeded_run_completed": True})

        self.assertEqual(result["verdict"], "UNRELATED_CRASH")
        self.assertFalse(result["evidence"]["loc0_match"])
        self.assertFalse(result["evidence"]["loc1_match"])
        self.assertFalse(result["evidence"]["crash_type_match"])

    def test_no_crash_after_completed_seeded_run_is_reached_no_crash(self) -> None:
        result = match_candidate(None, CANDIDATE, {"seeded_run_completed": True})

        self.assertEqual(result["verdict"], "REACHED_NO_CRASH")
        self.assertEqual(result["confidence"], "low")

    def test_setup_failed_takes_precedence(self) -> None:
        result = match_candidate(None, CANDIDATE, {"setup_failed": True})

        self.assertEqual(result["verdict"], "SETUP_FAILED")


if __name__ == "__main__":
    unittest.main()
