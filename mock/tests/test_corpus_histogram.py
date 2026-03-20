from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

MOCK_ROOT = Path(__file__).resolve().parents[1]
TOOL = MOCK_ROOT / "tools" / "corpus_histogram.py"


class CorpusHistogramTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="corpus-hist-"))
        self.left = self.tmpdir / "left"
        self.right = self.tmpdir / "right"
        (self.left / "corpus").mkdir(parents=True)
        (self.right / "corpus").mkdir(parents=True)
        (self.left / "corpus" / "a.prog").write_text(
            "openat$KVM(AT_FDCWD, '/dev/kvm', O_RDWR)\n"
            "ioctl$KVM_CREATE_VM(fd_kvm, KVM_CREATE_VM, 0)\n",
            encoding="utf-8",
        )
        (self.right / "corpus" / "a.prog").write_text(
            "openat$KVM(AT_FDCWD, '/dev/kvm', O_RDWR)\n"
            "ioctl$KVM_CREATE_VM(fd_kvm, KVM_CREATE_VM, 0)\n"
            "ioctl$KVM_CREATE_VCPU(fd_vm, KVM_CREATE_VCPU, 0)\n"
            "ioctl$KVM_RUN(fd_vcpu, KVM_RUN, 0)\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_single_summary_counts_kvm_calls(self) -> None:
        proc = subprocess.run(["python3", str(TOOL), str(self.left), "--json"], check=True, capture_output=True, text=True)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["program_count"], 1)
        self.assertEqual(payload["total_syscall_count"], 2)
        self.assertGreaterEqual(payload["kvm_family_counts"]["openat$KVM"], 1)
        self.assertGreaterEqual(payload["kvm_family_counts"]["KVM_CREATE_VM"], 1)

    def test_compare_mode_reports_deltas(self) -> None:
        proc = subprocess.run(["python3", str(TOOL), str(self.left), str(self.right), "--json"], check=True, capture_output=True, text=True)
        payload = json.loads(proc.stdout)
        self.assertIn("compare", payload)
        self.assertGreater(payload["compare"]["total_syscall_count_delta"], 0)
        self.assertGreater(payload["compare"]["kvm_family_deltas"]["KVM_CREATE_VCPU"], 0)
        self.assertGreater(payload["compare"]["kvm_family_deltas"]["KVM_RUN"], 0)


if __name__ == "__main__":
    unittest.main()
