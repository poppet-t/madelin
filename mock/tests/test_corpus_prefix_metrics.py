from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

MOCK_ROOT = Path(__file__).resolve().parents[1]
TOOL = MOCK_ROOT / "tools" / "corpus_prefix_metrics.py"


class CorpusPrefixMetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="corpus-prefix-"))
        self.direct = self.tmpdir / "direct"
        self.output_dir = self.tmpdir / "output"
        self.left = self.tmpdir / "left"
        self.right = self.tmpdir / "right"
        self.direct.mkdir(parents=True)
        (self.output_dir / "corpus").mkdir(parents=True)
        (self.left / "corpus").mkdir(parents=True)
        (self.right / "corpus").mkdir(parents=True)

        full_prefix = (
            "openat$KVM(AT_FDCWD, '/dev/kvm', O_RDWR)\n"
            "ioctl$KVM_CREATE_VM(fd_kvm, KVM_CREATE_VM, 0)\n"
            "ioctl$KVM_CREATE_VCPU(fd_vm, KVM_CREATE_VCPU, 0)\n"
            "ioctl$KVM_ARM_VCPU_INIT(fd_vcpu, KVM_ARM_VCPU_INIT, &init)\n"
            "ioctl$KVM_RUN(fd_vcpu, KVM_RUN, 0)\n"
        )
        partial_prefix = (
            "openat$KVM(AT_FDCWD, '/dev/kvm', O_RDWR)\n"
            "ioctl$KVM_CREATE_VM(fd_kvm, KVM_CREATE_VM, 0)\n"
            "close(fd_kvm)\n"
        )
        trigger_only = (
            "mmap$anon(0x0, 0x1000, 0x0, 0x0, -1, 0x0)\n"
            "ioctl$KVM_SET_ONE_REG(fd_vcpu, KVM_SET_ONE_REG, &one_reg)\n"
        )

        (self.direct / "a.prog").write_text(full_prefix, encoding="utf-8")
        (self.direct / "b.prog").write_text(partial_prefix, encoding="utf-8")
        (self.direct / "c.prog").write_text(trigger_only, encoding="utf-8")

        for child in self.direct.iterdir():
            (self.output_dir / "corpus" / child.name).write_text(
                child.read_text(encoding="utf-8"),
                encoding="utf-8",
            )

        (self.left / "corpus" / "a.prog").write_text(
            "openat$KVM(AT_FDCWD, '/dev/kvm', O_RDWR)\n"
            "close(fd_kvm)\n",
            encoding="utf-8",
        )
        (self.right / "corpus" / "a.prog").write_text(full_prefix, encoding="utf-8")
        (self.right / "corpus" / "b.prog").write_text(trigger_only, encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def run_tool(self, *args: str) -> dict:
        proc = subprocess.run(
            ["python3", str(TOOL), *args, "--json"],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(proc.stdout)

    def test_single_corpus_metrics_are_correct(self) -> None:
        payload = self.run_tool(str(self.direct))
        self.assertEqual(payload["program_count"], 3)
        self.assertEqual(payload["total_syscall_count"], 10)
        self.assertEqual(payload["kvm_related_total"], 8)
        self.assertEqual(payload["prefix_survival"]["prefix_1"]["count"], 2)
        self.assertEqual(payload["prefix_survival"]["prefix_2"]["count"], 2)
        self.assertEqual(payload["prefix_survival"]["prefix_3"]["count"], 1)
        self.assertEqual(payload["trigger_presence"]["programs_with_any_trigger"], 2)
        self.assertEqual(payload["kvm_family_counts"]["openat$KVM"], 2)
        self.assertEqual(payload["kvm_family_counts"]["KVM_CREATE_VM"], 2)
        self.assertEqual(payload["kvm_family_counts"]["KVM_CREATE_VCPU"], 1)
        self.assertEqual(payload["kvm_family_counts"]["KVM_RUN"], 1)
        self.assertEqual(payload["kvm_family_counts"]["KVM_SET_ONE_REG"], 1)

    def test_compare_mode_reports_positive_seeded_deltas(self) -> None:
        payload = self.run_tool(str(self.left), str(self.right))
        self.assertIn("compare", payload)
        self.assertGreater(payload["compare"]["prefix_survival_deltas"]["prefix_3"]["count_delta"], 0)
        self.assertGreater(payload["compare"]["programs_with_any_trigger_delta"], 0)
        self.assertGreater(payload["compare"]["kvm_related_total_delta"], 0)

    def test_json_shape_and_path_resolution(self) -> None:
        direct_payload = self.run_tool(str(self.direct))
        output_payload = self.run_tool(str(self.output_dir))
        self.assertIn("prefix_survival", direct_payload)
        self.assertIn("trigger_presence", direct_payload)
        self.assertIn("kvm_family_counts", direct_payload)
        self.assertIn("syscall_histogram", direct_payload)
        self.assertEqual(direct_payload["program_count"], output_payload["program_count"])
        self.assertEqual(direct_payload["total_syscall_count"], output_payload["total_syscall_count"])

        compare_payload = self.run_tool(str(self.left), str(self.right))
        self.assertIn("left", compare_payload)
        self.assertIn("right", compare_payload)
        self.assertIn("compare", compare_payload)
        self.assertIn("prefix_survival_deltas", compare_payload["compare"])
        self.assertIn("trigger_program_deltas", compare_payload["compare"])

    def test_mixed_non_corpus_dir_is_rejected(self) -> None:
        proc = subprocess.run(
            ["python3", str(TOOL), str(self.tmpdir), "--json"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("bad corpus/output dir", proc.stderr)


if __name__ == "__main__":
    unittest.main()
