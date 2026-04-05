#!/usr/bin/env python3
"""Unit tests for vm_validator modules.

These tests do NOT require a real VM. They test argument validation,
command construction, KASAN extraction, and graceful handling of
missing prerequisites.
"""

import json
import os
import pathlib
import socket
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from vm_validator.preflight import (
    check_file,
    check_qemu,
    check_ssh_key,
    run_preflight,
)
from vm_validator.vm_runner import (
    DEFAULT_SSH_PORT,
    build_qemu_cmd,
    classify_boot_failure,
    probe_ssh_banner,
    wait_for_ssh_command,
)
from vm_validator.prog_injector import build_inject_cmd, build_scp_cmd
from vm_validator.log_collector import extract_kasan, save_logs


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------

class TestCheckFile(unittest.TestCase):
    def test_existing_file(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"data")
            path = pathlib.Path(f.name)
        try:
            result = check_file(path, "test_file")
            self.assertTrue(result["ok"])
            self.assertEqual(result["name"], "test_file")
            self.assertIn("size_bytes", result)
        finally:
            path.unlink()

    def test_missing_file(self):
        result = check_file(pathlib.Path("/nonexistent/file.bin"), "missing")
        self.assertFalse(result["ok"])
        self.assertIn("not found", result["error"])

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            path = pathlib.Path(f.name)
        try:
            result = check_file(path, "empty")
            self.assertFalse(result["ok"])
            self.assertIn("empty", result["error"])
        finally:
            path.unlink()

    def test_directory_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            result = check_file(pathlib.Path(d), "dir")
            self.assertFalse(result["ok"])
            self.assertIn("not a regular file", result["error"])


class TestCheckSSHKey(unittest.TestCase):
    def test_good_permissions(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix="_key") as f:
            f.write(b"fake-key-data")
            path = pathlib.Path(f.name)
        try:
            os.chmod(path, 0o600)
            result = check_ssh_key(path)
            self.assertTrue(result["ok"])
        finally:
            path.unlink()

    def test_bad_permissions(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix="_key") as f:
            f.write(b"fake-key-data")
            path = pathlib.Path(f.name)
        try:
            os.chmod(path, 0o644)
            result = check_ssh_key(path)
            self.assertFalse(result["ok"])
            self.assertIn("too-open", result["error"])
        finally:
            path.unlink()


class TestRunPreflight(unittest.TestCase):
    def test_all_missing(self):
        result = run_preflight(
            kernel=pathlib.Path("/no/kernel"),
            disk_image=pathlib.Path("/no/disk"),
            ssh_key=pathlib.Path("/no/key"),
        )
        self.assertFalse(result["ready"])
        self.assertGreaterEqual(result["failed_count"], 3)

    def test_warning_when_no_execprog(self):
        result = run_preflight(
            kernel=pathlib.Path("/no/kernel"),
            disk_image=pathlib.Path("/no/disk"),
            ssh_key=pathlib.Path("/no/key"),
            syz_execprog=None,
        )
        self.assertTrue(any("syz_execprog" in w for w in result["warnings"]))

    def test_qemu_check_runs(self):
        result = check_qemu()
        # This should always return a dict, whether qemu is installed or not.
        self.assertIn("ok", result)
        self.assertEqual(result["name"], "qemu")


# ---------------------------------------------------------------------------
# vm_runner — command construction
# ---------------------------------------------------------------------------

class TestBuildQemuCmd(unittest.TestCase):
    def setUp(self):
        self.cmd = build_qemu_cmd(
            kernel=pathlib.Path("/path/to/Image"),
            disk_image=pathlib.Path("/path/to/disk.qcow2"),
            ssh_port=10022,
        )

    def test_binary(self):
        self.assertEqual(self.cmd[0], "qemu-system-aarch64")

    def test_machine_virt(self):
        idx = self.cmd.index("-machine")
        self.assertEqual(self.cmd[idx + 1], "virt")

    def test_accel_tcg(self):
        idx = self.cmd.index("-accel")
        self.assertEqual(self.cmd[idx + 1], "tcg")

    def test_nographic(self):
        self.assertIn("-nographic", self.cmd)

    def test_no_reboot(self):
        self.assertIn("-no-reboot", self.cmd)

    def test_ssh_port_forwarding(self):
        joined = " ".join(self.cmd)
        self.assertIn("10022", joined)
        self.assertIn("hostfwd", joined)

    def test_kernel_path(self):
        idx = self.cmd.index("-kernel")
        self.assertEqual(self.cmd[idx + 1], "/path/to/Image")

    def test_kasan_fault_panic(self):
        idx = self.cmd.index("-append")
        append = self.cmd[idx + 1]
        self.assertIn("kasan.fault=panic", append)

    def test_custom_port(self):
        cmd = build_qemu_cmd(
            kernel=pathlib.Path("/k"),
            disk_image=pathlib.Path("/d"),
            ssh_port=22222,
        )
        joined = " ".join(cmd)
        self.assertIn("22222", joined)

    def test_console_log(self):
        cmd = build_qemu_cmd(
            kernel=pathlib.Path("/k"),
            disk_image=pathlib.Path("/d"),
            console_log=pathlib.Path("/tmp/console.log"),
        )
        self.assertIn("-serial", cmd)
        self.assertIn("file:/tmp/console.log", cmd)

    def test_default_append_does_not_force_custom_init(self):
        idx = self.cmd.index("-append")
        append = self.cmd[idx + 1]
        self.assertNotIn("init=/root/madelin-guest-init.sh", append)


class TestSshReadiness(unittest.TestCase):
    def test_probe_ssh_banner_timeout_classified(self):
        with mock.patch("vm_validator.vm_runner.socket.create_connection") as create_connection:
            conn = mock.MagicMock()
            conn.__enter__.return_value = conn
            conn.recv.side_effect = socket.timeout()
            create_connection.return_value = conn
            result = probe_ssh_banner(port=2222, timeout=0.1)
        self.assertFalse(result["ok"])
        self.assertTrue(result["connected"])
        self.assertEqual(result["error"], "banner timeout")

    def test_wait_for_ssh_command_reports_banner_timeout(self):
        with mock.patch(
            "vm_validator.vm_runner.probe_ssh_banner",
            return_value={"ok": False, "connected": True, "error": "banner timeout", "banner": ""},
        ), mock.patch(
            "vm_validator.vm_runner.probe_ssh_command",
            return_value={"ok": False, "stderr": "banner exchange", "stdout": "", "failure_class": "ssh_banner_timeout", "error": "banner exchange"},
        ):
            result = wait_for_ssh_command(
                ssh_key=pathlib.Path("/tmp/fake"),
                timeout=0.01,
                poll_interval=0.01,
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["failure_class"], "ssh_banner_timeout")

    def test_wait_for_ssh_command_succeeds_with_socket_activated_ssh(self):
        with mock.patch(
            "vm_validator.vm_runner.probe_ssh_banner",
            side_effect=[
                {"ok": False, "connected": True, "error": "banner timeout", "banner": ""},
            ],
        ), mock.patch(
            "vm_validator.vm_runner.probe_ssh_command",
            return_value={"ok": True, "stderr": "", "stdout": "", "failure_class": None},
        ):
            result = wait_for_ssh_command(
                ssh_key=pathlib.Path("/tmp/fake"),
                timeout=0.05,
                poll_interval=0.01,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["timeline"][0]["banner_error"], "banner timeout")

    def test_classify_boot_failure_missing_init(self):
        result = classify_boot_failure(
            console_excerpt=["Kernel panic - not syncing: Requested init /root/madelin-guest-init.sh failed (error -2)."],
        )
        self.assertEqual(result["failure_class"], "custom_init_missing")

    def test_classify_boot_failure_emergency_mode(self):
        result = classify_boot_failure(
            console_excerpt=["You are in emergency mode. After logging in, type journalctl -xb to view"],
        )
        self.assertEqual(result["failure_class"], "systemd_emergency_mode")

    def test_wait_for_ssh_command_succeeds_on_real_probe(self):
        with mock.patch(
            "vm_validator.vm_runner.probe_ssh_banner",
            side_effect=[
                {"ok": False, "connected": False, "error": "connection refused", "banner": ""},
                {"ok": True, "connected": True, "error": None, "banner": "SSH-2.0-OpenSSH_9.6"},
            ],
        ), mock.patch(
            "vm_validator.vm_runner.probe_ssh_command",
            return_value={"ok": True, "stderr": "", "stdout": "", "failure_class": None},
        ):
            result = wait_for_ssh_command(
                ssh_key=pathlib.Path("/tmp/fake"),
                timeout=0.05,
                poll_interval=0.01,
            )
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(len(result["timeline"]), 2)


# ---------------------------------------------------------------------------
# prog_injector — command construction
# ---------------------------------------------------------------------------

class TestInjectCommands(unittest.TestCase):
    def test_ssh_cmd(self):
        cmd = build_inject_cmd(
            ssh_port=10022,
            ssh_key=pathlib.Path("/path/to/key"),
        )
        self.assertEqual(cmd[0], "ssh")
        self.assertIn("-p", cmd)
        idx = cmd.index("-p")
        self.assertEqual(cmd[idx + 1], "10022")
        self.assertIn("root@127.0.0.1", cmd)

    def test_scp_cmd(self):
        cmd = build_scp_cmd(
            local_path=pathlib.Path("/local/seed.prog"),
            remote_path="/root/seed.prog",
            ssh_port=10022,
            ssh_key=pathlib.Path("/path/to/key"),
        )
        self.assertEqual(cmd[0], "scp")
        self.assertIn("-P", cmd)
        self.assertIn("/local/seed.prog", cmd)
        self.assertIn("root@127.0.0.1:/root/seed.prog", cmd)

    def test_strict_host_key_disabled(self):
        cmd = build_inject_cmd(ssh_port=10022, ssh_key=pathlib.Path("/k"))
        self.assertIn("StrictHostKeyChecking=no", cmd)


# ---------------------------------------------------------------------------
# log_collector — KASAN extraction
# ---------------------------------------------------------------------------

class TestExtractKasan(unittest.TestCase):
    def test_no_kasan(self):
        self.assertIsNone(extract_kasan("normal kernel log\nnothing here\n"))

    def test_empty_string(self):
        self.assertIsNone(extract_kasan(""))

    def test_none_like(self):
        self.assertIsNone(extract_kasan(""))

    def test_kasan_detected(self):
        dmesg = (
            "[  1.0] booting\n"
            "[  2.0] BUG: KASAN: use-after-free in some_func+0x10/0x20\n"
            "[  2.1] Read of size 8 at addr ffff0000deadbeef\n"
            "[  2.2] Call Trace:\n"
            "[  2.3]  some_func+0x10/0x20\n"
            "[  2.4]  caller_func+0x30/0x40\n"
            "[  2.5] ====================================\n"
            "[  3.0] more stuff\n"
        )
        result = extract_kasan(dmesg)
        self.assertIsNotNone(result)
        self.assertIn("BUG: KASAN", result)
        self.assertIn("some_func", result)

    def test_kasan_without_separator(self):
        dmesg = (
            "[  2.0] BUG: KASAN: use-after-free in f+0x10\n"
            "[  2.1] Read of size 4\n"
        )
        result = extract_kasan(dmesg)
        self.assertIsNotNone(result)
        self.assertIn("BUG: KASAN", result)


class TestSaveLogs(unittest.TestCase):
    def test_save_dmesg_only(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d) / "run"
            result = save_logs(out, dmesg="kernel log\n", kasan_excerpt=None)
            self.assertTrue((out / "guest_dmesg.txt").exists())
            self.assertFalse((out / "crash_log.txt").exists())

    def test_save_with_kasan(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d) / "run"
            result = save_logs(out, dmesg="log\n", kasan_excerpt="BUG: KASAN\n")
            self.assertTrue((out / "crash_log.txt").exists())
            self.assertEqual((out / "crash_log.txt").read_text(), "BUG: KASAN\n")

    def test_save_execprog_output(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d) / "run"
            result = save_logs(
                out, dmesg="log\n", kasan_excerpt=None,
                execprog_stdout="out\n", execprog_stderr="err\n",
            )
            self.assertTrue((out / "execprog_stdout.txt").exists())
            self.assertTrue((out / "execprog_stderr.txt").exists())


if __name__ == "__main__":
    unittest.main()
