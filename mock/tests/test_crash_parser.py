from __future__ import annotations

import unittest

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

Allocated by task 1234:
 kvm_vm_ioctl_create_vcpu+0xe4/0x240 virt/kvm/kvm_main.c:511
"""

SLAB_OOB_LOG = """BUG: KASAN: slab-out-of-bounds in unrelated_driver_ioctl+0x10/0x40 drivers/net/unrelated.c:55
Write of size 16 at addr 0xffff000043210000 by task syz-executor/77

Call trace:
 unrelated_driver_ioctl+0x10/0x40 drivers/net/unrelated.c:55
 vfs_ioctl+0x44/0x90 fs/ioctl.c:51
"""

NULL_DEREF_LOG = """Unable to handle kernel NULL pointer dereference at virtual address 0000000000000000
Call trace:
 do_bad_thing+0x18/0x40 drivers/misc/demo.c:41
 do_other_thing+0x20/0x70 drivers/misc/demo.c:58
"""


class CrashParserTests(unittest.TestCase):
    def test_parse_matching_kasan_uaf_report(self) -> None:
        parsed = parse_crash_text(MATCHING_UAF_LOG)

        self.assertEqual(parsed["crash_type"], "use-after-free")
        self.assertEqual(parsed["access"], "read")
        self.assertEqual(parsed["faulting_address"], "0xffff000012340000")
        self.assertEqual(parsed["stack_frames"][1]["function"], "kvm_timer_should_fire")
        self.assertEqual(parsed["free_stack"][1]["function"], "kvm_timer_vcpu_terminate")
        self.assertEqual(parsed["alloc_stack"][0]["function"], "kvm_vm_ioctl_create_vcpu")

    def test_parse_slab_oob_report(self) -> None:
        parsed = parse_crash_text(SLAB_OOB_LOG)

        self.assertEqual(parsed["crash_type"], "slab-out-of-bounds")
        self.assertEqual(parsed["access"], "write")
        self.assertEqual(parsed["stack_frames"][0]["function"], "unrelated_driver_ioctl")

    def test_parse_null_deref_report(self) -> None:
        parsed = parse_crash_text(NULL_DEREF_LOG)

        self.assertEqual(parsed["crash_type"], "null-deref")
        self.assertIsNone(parsed["access"])
        self.assertEqual(parsed["stack_frames"][0]["function"], "do_bad_thing")


if __name__ == "__main__":
    unittest.main()
