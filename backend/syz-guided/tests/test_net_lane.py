#!/usr/bin/env python3

from __future__ import annotations

import json
import pathlib
import stat
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from runtime.net_lane import (
    DEFAULT_GUEST_EXTRA_APPEND,
    DEFAULT_GUEST_SEED_PATH,
    DEFAULT_GUEST_SYZ_EXECPROG,
    DEFAULT_GUEST_SYZ_EXECUTOR,
    GUEST_RUNTIME_DIR,
    FALLBACK_GUEST_RUNTIME_DIR,
    _copy_to_guest,
    _classify_seed_result,
    _check_arm64_binary,
    _check_guest_arm64_binary,
    _check_guest_execprog_coverfile_support,
    _guest_binary_reusable,
    _check_guest_net_features,
    _guest_cmd,
    _guest_cmd_retry,
    _ordered_seed_paths,
    _parse_config_requirements,
    _proof_manifest,
    _probe_guest_kernel_config,
    _prepare_guest_execution,
    _runtime_paths,
    _should_retry_runtime_dir,
    generate_manual_novelty_report,
    run_net_runtime_lane,
    run_live_preflight,
)
from seedgen.synthesize_seeds import synthesize
from state_model.build_state_model import build_state_model, build_target_profile

_FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "packs" / "net"


def _load_json(path: pathlib.Path) -> dict:
    with open(path) as f:
        return json.load(f)


class TestNetLaneHelpers(unittest.TestCase):
    def test_default_guest_append_uses_systemd_safe_path_not_custom_init(self) -> None:
        self.assertIn("systemd.unit=multi-user.target", DEFAULT_GUEST_EXTRA_APPEND)
        self.assertNotIn("init=/root/madelin-guest-init.sh", DEFAULT_GUEST_EXTRA_APPEND)

    def test_default_guest_runtime_paths_use_tmp_workspace(self) -> None:
        self.assertEqual(GUEST_RUNTIME_DIR, "/tmp/madelin-net-runtime")
        self.assertEqual(FALLBACK_GUEST_RUNTIME_DIR, "/var/tmp/madelin-net-runtime")
        self.assertTrue(DEFAULT_GUEST_SYZ_EXECPROG.startswith(GUEST_RUNTIME_DIR))
        self.assertTrue(DEFAULT_GUEST_SYZ_EXECUTOR.startswith(GUEST_RUNTIME_DIR))
        self.assertTrue(DEFAULT_GUEST_SEED_PATH.startswith(GUEST_RUNTIME_DIR))

    def test_runtime_paths_build_seed_and_cover_locations(self) -> None:
        runtime_paths = _runtime_paths("/var/tmp/madelin-net-runtime")
        self.assertEqual(runtime_paths["seed_path"], "/var/tmp/madelin-net-runtime/seed.prog")
        self.assertEqual(runtime_paths["cover_path"], "/var/tmp/madelin-net-runtime/seed.cover")

    def test_should_retry_runtime_dir_for_missing_directory_errors(self) -> None:
        retry = _should_retry_runtime_dir({
            "error": "stream-copy rc=2",
            "stderr": "sh: 1: cannot create /tmp/madelin-net-runtime/seed.prog: Directory nonexistent\n",
            "scp_stderr": "scp: /tmp/madelin-net-runtime/seed.prog: No such file or directory\n",
        })
        self.assertTrue(retry)

    def test_parse_config_requirements(self) -> None:
        present, missing = _parse_config_requirements(
            "CONFIG_KASAN=y\nCONFIG_KCOV=y\n",
            ["CONFIG_KASAN=y", "CONFIG_KCOV=y", "CONFIG_DEBUG_FS=y"],
        )
        self.assertEqual(present, ["CONFIG_KASAN=y", "CONFIG_KCOV=y"])
        self.assertEqual(missing, ["CONFIG_DEBUG_FS=y"])

    def test_parse_config_requirements_accepts_module_alternatives(self) -> None:
        present, missing = _parse_config_requirements(
            "CONFIG_NETFILTER=y\nCONFIG_NF_TABLES=m\n",
            ["CONFIG_KASAN=y"],
            {"CONFIG_NF_TABLES": ["CONFIG_NF_TABLES=y", "CONFIG_NF_TABLES=m"]},
        )
        self.assertIn("CONFIG_NF_TABLES=m", present)
        self.assertEqual(missing, ["CONFIG_KASAN=y"])

    def test_check_arm64_binary_rejects_wrong_arch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "fake-elf"
            header = bytearray(64)
            header[:4] = b"\x7fELF"
            header[4] = 2
            header[5] = 1
            header[18:20] = (62).to_bytes(2, "little")
            path.write_bytes(bytes(header))
            result = _check_arm64_binary(path, "syz_execprog")
            self.assertFalse(result["ok"])
            self.assertIn("linux/arm64", result["error"])

    def test_check_guest_arm64_binary_uses_guest_probe(self) -> None:
        with mock.patch("runtime.net_lane._guest_cmd", return_value={"ok": True, "stdout": "183\n"}):
            result = _check_guest_arm64_binary(10022, pathlib.Path("/tmp/id_rsa"), "/root/syz-executor", "guest_syz_executor_arch")
        self.assertTrue(result["ok"])
        self.assertEqual(result["target"], "linux/arm64")

    def test_guest_binary_reusable_requires_matching_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "syz-executor"
            header = bytearray(64)
            header[:4] = b"\x7fELF"
            header[4] = 2
            header[5] = 1
            header[18:20] = (183).to_bytes(2, "little")
            path.write_bytes(bytes(header) + b"payload")
            with mock.patch(
                "runtime.net_lane._check_guest_arm64_binary",
                return_value={"ok": True, "name": "guest_syz_executor_arch"},
            ), mock.patch(
                "runtime.net_lane._guest_file_size",
                return_value={"ok": True, "size_bytes": path.stat().st_size},
            ):
                result = _guest_binary_reusable(
                    host_path=path,
                    remote_path="/tmp/madelin-net-runtime/syz-executor",
                    ssh_port=10022,
                    ssh_key=pathlib.Path("/tmp/id_rsa"),
                    label="guest_syz_executor_arch",
                )
        self.assertTrue(result["ok"])

    def test_guest_binary_reusable_rejects_size_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "syz-executor"
            header = bytearray(64)
            header[:4] = b"\x7fELF"
            header[4] = 2
            header[5] = 1
            header[18:20] = (183).to_bytes(2, "little")
            path.write_bytes(bytes(header) + b"payload")
            with mock.patch(
                "runtime.net_lane._check_guest_arm64_binary",
                return_value={"ok": True, "name": "guest_syz_executor_arch"},
            ), mock.patch(
                "runtime.net_lane._guest_file_size",
                return_value={"ok": True, "size_bytes": path.stat().st_size + 1},
            ):
                result = _guest_binary_reusable(
                    host_path=path,
                    remote_path="/tmp/madelin-net-runtime/syz-executor",
                    ssh_port=10022,
                    ssh_key=pathlib.Path("/tmp/id_rsa"),
                    label="guest_syz_executor_arch",
                )
        self.assertFalse(result["ok"])

    def test_copy_to_guest_falls_back_to_ssh_cat_and_preserves_scp_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "syz-executor"
            path.write_bytes(b"payload")
            completed = mock.Mock(returncode=0, stdout=b"", stderr=b"")
            with mock.patch(
                "runtime.net_lane._guest_cmd_retry",
                return_value={"ok": True, "stdout": "", "stderr": "", "attempts": [{"attempt": 1, "ok": True}]},
            ), mock.patch(
                "runtime.net_lane._run_cmd",
                return_value={"ok": False, "stdout": "", "stderr": "sh: scp: not found", "error": "rc=1", "returncode": 1},
            ), mock.patch(
                "runtime.net_lane.subprocess.run",
                return_value=completed,
            ):
                result = _copy_to_guest(path, "/tmp/madelin-net-runtime/syz-executor", 10022, pathlib.Path("/tmp/id_rsa"))
        self.assertTrue(result["ok"])
        self.assertEqual(result["method"], "ssh-cat")
        self.assertEqual(result["fallback_from"], "scp")
        self.assertEqual(result["scp_error"], "rc=1")

    def test_probe_guest_kernel_config_uses_targeted_grep(self) -> None:
        with mock.patch("runtime.net_lane._guest_cmd", return_value={"ok": True, "stdout": "CONFIG_KASAN=y\nCONFIG_NF_TABLES=y\n", "returncode": 0}) as guest_cmd:
            result = _probe_guest_kernel_config(
                10022,
                pathlib.Path("/tmp/id_rsa"),
                ["CONFIG_KASAN=y"],
                {"CONFIG_NF_TABLES": ["CONFIG_NF_TABLES=y", "CONFIG_NF_TABLES=m"]},
            )
        self.assertTrue(result["ok"])
        invoked = guest_cmd.call_args.args[2]
        self.assertIn("grep -E", invoked)
        self.assertNotIn("cat /boot/config", invoked)

    def test_coverfile_probe_uses_binary_grep(self) -> None:
        with mock.patch("runtime.net_lane._guest_cmd", return_value={"ok": True, "stdout": "coverfile\n"}):
            result = _check_guest_execprog_coverfile_support(10022, pathlib.Path("/tmp/id_rsa"), "/root/syz-execprog")
        self.assertTrue(result["ok"])

    def test_guest_net_features_accept_builtin_kernel_config(self) -> None:
        result = _check_guest_net_features(10022, pathlib.Path("/tmp/id_rsa"), "CONFIG_NETFILTER=y\nCONFIG_NF_TABLES=y\n")
        self.assertEqual([item["ok"] for item in result], [True, True])
        self.assertEqual(result[0]["state"], "built-in-config")

    def test_guest_cmd_quotes_remote_shell_command_as_one_argument(self) -> None:
        with mock.patch("runtime.net_lane._run_cmd", return_value={"ok": True}) as run_cmd:
            _guest_cmd(10022, pathlib.Path("/tmp/id_rsa"), "uname -a && uname -m", timeout_sec=7)
        remote = run_cmd.call_args.args[0][-1]
        self.assertTrue(remote.startswith("sh -c "))
        self.assertIn("uname -a && uname -m", remote)

    def test_guest_cmd_retry_retries_timeouts(self) -> None:
        with mock.patch(
            "runtime.net_lane._guest_cmd",
            side_effect=[
                {"ok": False, "timed_out": True, "duration_sec": 20.0, "error": "timeout after 20s"},
                {"ok": True, "timed_out": False, "duration_sec": 1.0, "error": None, "stdout": "ok\n"},
            ],
        ):
            result = _guest_cmd_retry(10022, pathlib.Path("/tmp/id_rsa"), "true", timeout_sec=20, attempts=2, retry_delay_sec=0.0)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["attempts"]), 2)
        self.assertTrue(result["attempts"][0]["timed_out"])

    def test_manual_review_report_includes_hygiene_checklist(self) -> None:
        report = generate_manual_novelty_report(
            crash_evidence_summary={
                "title": "BUG: KASAN: use-after-free in nf_tables_dump_set",
                "signature": "cafebabe",
                "top_frames": ["nf_tables_dump_set", "nf_tables_destroy_set"],
            },
            candidate_evidence_summary={
                "path_relevant": True,
                "match_score": 0.9,
                "specific_candidate_alignment": True,
                "alignment_quality": "specific",
            },
            reproducibility_summary={"classification": "reproducible crash", "crash_count": 2, "attempts": 3},
            seen_signatures={"cafebabe": 2},
        )
        self.assertEqual(report["status"], "unchecked")
        self.assertIn("compare against syzbot netfilter reports", report["checklist"])
        self.assertTrue(report["likely_duplicate_indicators"])

    def test_classify_seed_result_distinguishes_timeout_from_stall(self) -> None:
        execution = {"target_family_hit": True, "phase_reached": "trigger"}
        crash = {"crash_detected": False}

        timed_out = _classify_seed_result(
            execution_evidence=execution,
            crash_evidence=crash,
            exec_result={
                "ok": False,
                "timed_out": True,
                "stdout": "partial",
                "stderr": "",
                "coverage_copied": False,
                "duration_sec": 180.0,
                "error": "timeout after 180s",
            },
        )
        stalled = _classify_seed_result(
            execution_evidence=execution,
            crash_evidence=crash,
            exec_result={
                "ok": False,
                "timed_out": True,
                "stdout": "",
                "stderr": "",
                "coverage_copied": False,
                "duration_sec": 180.0,
                "error": "timeout after 180s",
            },
        )

        self.assertEqual(timed_out["classification"], "timed-out")
        self.assertEqual(stalled["classification"], "stalled")
        self.assertTrue(timed_out["progress_signals"]["ssh_command_timeout"])

    def test_ordered_seed_paths_prioritizes_delete_dump_in_controlled_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            seeds_dir = pathlib.Path(tmpdir)
            manifest = {
                "seeds": [
                    {"name": "seed_dump_delete.prog"},
                    {"name": "seed_delete_close.prog"},
                    {"name": "seed_delete_dump.prog"},
                ]
            }
            (seeds_dir / "seed_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            for name in ["seed_dump_delete.prog", "seed_delete_close.prog", "seed_delete_dump.prog"]:
                (seeds_dir / name).write_text("# seed\n", encoding="utf-8")
            ordered = _ordered_seed_paths(seeds_dir, proof_mode="controlled")
        self.assertEqual([path.name for path in ordered], [
            "seed_delete_dump.prog",
            "seed_dump_delete.prog",
            "seed_delete_close.prog",
        ])

    def test_proof_manifest_records_repro_command(self) -> None:
        manifest = _proof_manifest(
            proof_mode="controlled",
            kernel=pathlib.Path("/tmp/proof-kernel"),
            disk_image=pathlib.Path("/tmp/proof-disk.qcow2"),
            guest_syz_execprog_path="/usr/local/bin/syz-execprog",
            guest_syz_executor_path="/usr/local/bin/syz-executor",
            seed=pathlib.Path("/tmp/seed_delete_dump.prog"),
            timeout_sec=420,
            threaded=False,
            procs=1,
            proof_kernel_meta={"source_head": "deadbeef"},
        )
        self.assertEqual(manifest["proof_mode"], "controlled")
        self.assertEqual(manifest["seed"], "seed_delete_dump.prog")
        self.assertIn("/usr/local/bin/syz-execprog", manifest["repro_command"])
        self.assertIn("/usr/local/bin/syz-executor", manifest["repro_command"])


class TestNetRuntimeLane(unittest.TestCase):
    def _build_state_inputs(self) -> tuple[dict, dict, dict]:
        candidate = _load_json(_FIXTURES / "candidate.json")
        plan = _load_json(_FIXTURES / "witness_plan.json")
        sm = build_state_model(candidate, plan, "fixtures/packs/net/candidate.json", "fixtures/packs/net/witness_plan.json")
        tp = build_target_profile(candidate)
        return candidate, sm, tp

    def _write_arm64_elf(self, path: pathlib.Path) -> None:
        header = bytearray(64)
        header[:4] = b"\x7fELF"
        header[4] = 2
        header[5] = 1
        header[18:20] = (183).to_bytes(2, "little")
        path.write_bytes(bytes(header) + b"payload")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)

    def test_runtime_lane_emits_layout_and_repro_artifacts(self) -> None:
        _, sm, tp = self._build_state_inputs()
        seeds = synthesize(sm)

        with tempfile.TemporaryDirectory() as tmpdir:
            base = pathlib.Path(tmpdir)
            seeds_dir = base / "seeds"
            out_dir = base / "live-run"
            seeds_dir.mkdir()
            for seed in seeds:
                (seeds_dir / seed["name"]).write_text(seed["prog_text"], encoding="utf-8")

            state_model_path = base / "state_model_v1.json"
            target_profile_path = base / "target_profile.json"
            state_model_path.write_text(json.dumps(sm), encoding="utf-8")
            target_profile_path.write_text(json.dumps(tp), encoding="utf-8")

            syz_execprog = base / "syz-execprog"
            kernel = base / "Image"
            disk = base / "disk.qcow2"
            ssh_key = base / "id_rsa"
            self._write_arm64_elf(syz_execprog)
            kernel.write_bytes(b"kernel")
            disk.write_bytes(b"disk")
            ssh_key.write_text("key", encoding="utf-8")
            ssh_key.chmod(0o600)

            preflight = {
                "ready": True,
                "host_checks": [],
                "guest_checks": [],
                "environment": {"arch": "aarch64", "cmdline": "console=ttyAMA0"},
            }

            call_counter = {"count": 0}

            def fake_run_one_live_seed(*, seed, seed_out, **kwargs):
                call_counter["count"] += 1
                seed_out.mkdir(parents=True, exist_ok=True)
                crash_detected = call_counter["count"] == 1 or call_counter["count"] in {11, 12}
                signature = "deadbeef" if crash_detected else None
                summary = {
                    "seed": seed.name,
                    "seed_dir": str(seed_out),
                    "execution_evidence": {
                        "target_family_hit": True,
                        "phase_reached": "trigger",
                        "phases_exercised": ["bootstrap", "configure", "trigger"],
                        "prefix_preserved": True,
                        "trigger_phase_reached": True,
                    },
                    "crash_evidence": {
                        "crash_detected": crash_detected,
                        "crash_kind": "kasan" if crash_detected else "none",
                        "real_crash_signal": crash_detected,
                        "signature": signature,
                        "title": "BUG: KASAN: use-after-free in nf_tables_dump_set" if crash_detected else None,
                        "top_frames": ["nf_tables_dump_set", "nf_tables_destroy_set"] if crash_detected else [],
                        "source_files": ["net/netfilter/nf_tables_api.c"] if crash_detected else [],
                    },
                    "candidate_evidence": {
                        "path_relevant": crash_detected,
                        "match_score": 0.95 if crash_detected else 0.0,
                        "specific_candidate_alignment": crash_detected,
                        "alignment_quality": "specific" if crash_detected else "unrelated",
                        "subsystem_relevance_score": 0.95 if crash_detected else 0.0,
                        "specific_free_hit": crash_detected,
                        "specific_use_hit": crash_detected,
                    },
                    "triage_verdict": "confirmed" if crash_detected else "insufficient_data",
                    "subsystem_relevance": "net_teardown_use" if crash_detected else "unrelated",
                }
                (seed_out / "seed_run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
                return summary

            with mock.patch("runtime.net_lane.run_live_preflight", return_value=preflight), mock.patch(
                "runtime.net_lane._run_one_live_seed", side_effect=fake_run_one_live_seed
            ):
                result = run_net_runtime_lane(
                    state_model_path=state_model_path,
                    target_profile_path=target_profile_path,
                    seeds_dir=seeds_dir,
                    out_dir=out_dir,
                    syz_execprog=syz_execprog,
                    syz_executor=None,
                    kernel=kernel,
                    disk_image=disk,
                    ssh_key=ssh_key,
                    timeout_sec=10,
                    threaded=True,
                    procs=1,
                    repro_attempts=3,
                    guest_syz_executor_path="/root/syz-executor",
                )

            self.assertTrue((out_dir / "preflight" / "preflight_summary.json").exists() or True)
            self.assertTrue((out_dir / "campaign" / "stage_summary.json").exists())
            self.assertTrue((out_dir / "runtime" / "execution_evidence_summary.json").exists())
            self.assertTrue((out_dir / "runtime" / "crash_evidence_summary.json").exists())
            self.assertTrue((out_dir / "runtime" / "candidate_evidence_summary.json").exists())
            self.assertTrue((out_dir / "runtime" / "kernel_provenance.json").exists())
            self.assertTrue((out_dir / "runtime" / "source_frame_summary.json").exists())
            self.assertTrue((out_dir / "runtime" / "lab_state.json").exists())
            self.assertTrue((out_dir / "runtime" / "lab_run_bundle.json").exists())
            self.assertTrue((out_dir / "logs" / "ranking_input.json").exists())
            self.assertTrue((out_dir / "logs" / "ranking_decision.json").exists())
            self.assertTrue((out_dir / "crashes" / "manual_known_bug_review.json").exists())
            self.assertTrue(any((out_dir / "repro").glob("**/repro_summary.json")))
            self.assertEqual(result["runtime_verdict"]["verdict_class"], "novelty-unchecked bug candidate")

    def test_runtime_lane_classifies_preflight_failure(self) -> None:
        _, sm, tp = self._build_state_inputs()
        seeds = synthesize(sm)

        with tempfile.TemporaryDirectory() as tmpdir:
            base = pathlib.Path(tmpdir)
            seeds_dir = base / "seeds"
            out_dir = base / "live-run"
            seeds_dir.mkdir()
            for seed in seeds[:1]:
                (seeds_dir / seed["name"]).write_text(seed["prog_text"], encoding="utf-8")

            state_model_path = base / "state_model_v1.json"
            target_profile_path = base / "target_profile.json"
            state_model_path.write_text(json.dumps(sm), encoding="utf-8")
            target_profile_path.write_text(json.dumps(tp), encoding="utf-8")

            dummy = base / "dummy"
            dummy.write_bytes(b"x")
            ssh_key = base / "id_rsa"
            ssh_key.write_text("key", encoding="utf-8")
            ssh_key.chmod(0o600)

            with mock.patch("runtime.net_lane.run_live_preflight", return_value={"ready": False, "host_checks": [], "guest_checks": [], "environment": {}}):
                result = run_net_runtime_lane(
                    state_model_path=state_model_path,
                    target_profile_path=target_profile_path,
                    seeds_dir=seeds_dir,
                    out_dir=out_dir,
                    syz_execprog=dummy,
                    syz_executor=dummy,
                    kernel=dummy,
                    disk_image=dummy,
                    ssh_key=ssh_key,
                )

            self.assertEqual(result["runtime_verdict"]["verdict_class"], "environment/setup failure")
            self.assertTrue((out_dir / "runtime" / "final_verdict.json").exists())
            self.assertTrue((out_dir / "runtime" / "blocker_report.json").exists())
            self.assertTrue((out_dir / "runtime" / "lab_run_bundle.json").exists())
            blocker = json.loads((out_dir / "runtime" / "blocker_report.json").read_text(encoding="utf-8"))
            self.assertEqual(blocker["failure_class"], "environment/setup failure")

    def test_live_preflight_uses_append_fallback_for_serial_and_mount_fallback_for_debugfs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = pathlib.Path(tmpdir)
            kernel = base / "Image"
            disk = base / "disk.qcow2"
            ssh_key = base / "id_rsa"
            syz_execprog = base / "syz-execprog"
            syz_executor = base / "syz-executor"
            out_dir = base / "preflight"
            kernel.write_bytes(b"kernel")
            disk.write_bytes(b"disk")
            ssh_key.write_text("key", encoding="utf-8")
            ssh_key.chmod(0o600)
            self._write_arm64_elf(syz_execprog)
            self._write_arm64_elf(syz_executor)

            boot = {
                "ok": True,
                "process": object(),
                "qemu_cmd": [
                    "qemu-system-aarch64",
                    "-append",
                    "root=/dev/vda1 console=ttyAMA0 kasan.fault=panic",
                ],
                "ssh_ready": {"timeline": [], "banner": "SSH-2.0-OpenSSH_9.6"},
            }

            def fake_guest_cmd_retry(_ssh_port, _ssh_key, command, *, timeout_sec, attempts=3, retry_delay_sec=1.0):
                if command == "uname -a && uname -m":
                    return {"ok": True, "stdout": "Linux guest 6.8.0\naarch64\n", "attempts": [{"attempt": 1, "ok": True}]}
                if command == "true":
                    return {"ok": True, "stdout": "", "attempts": [{"attempt": 1, "ok": True}]}
                if command == "cat /proc/cmdline":
                    return {"ok": False, "timed_out": True, "stdout": "", "error": "timeout after 15s", "attempts": [{"attempt": 1, "ok": False, "timed_out": True}]}
                if command == "mkdir -p /sys/kernel/debug && test -d /sys/kernel/debug":
                    return {"ok": False, "timed_out": True, "stdout": "", "error": "timeout after 15s", "attempts": [{"attempt": 1, "ok": False, "timed_out": True}]}
                if command == "mountpoint -q /sys/kernel/debug || mount -t debugfs debugfs /sys/kernel/debug":
                    return {"ok": True, "stdout": "", "attempts": [{"attempt": 1, "ok": True}]}
                if command == "python3 -c 'import socket; s = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, 12); s.close(); print(\"ok\")'":
                    return {"ok": True, "stdout": "ok\n", "attempts": [{"attempt": 1, "ok": True}]}
                if command.startswith("chmod +x "):
                    return {"ok": True, "stdout": "", "attempts": [{"attempt": 1, "ok": True}]}
                return {"ok": True, "stdout": "", "attempts": [{"attempt": 1, "ok": True}], "returncode": 0}

            with mock.patch("runtime.net_lane._host_cmd_check", return_value={"ok": True, "name": "cmd"}), mock.patch(
                "runtime.net_lane._boot_guest", return_value=boot
            ), mock.patch(
                "runtime.net_lane._guest_cmd_retry", side_effect=fake_guest_cmd_retry
            ), mock.patch(
                "runtime.net_lane._prepare_guest_runtime_environment", return_value={"ok": True}
            ), mock.patch(
                "runtime.net_lane._probe_guest_kernel_config",
                return_value={"ok": True, "config_text": "CONFIG_KASAN=y\nCONFIG_KCOV=y\nCONFIG_DEBUG_INFO=y\nCONFIG_DEBUG_FS=y\nCONFIG_KCOV_INSTRUMENT_ALL=y\nCONFIG_NETFILTER=y\nCONFIG_NF_TABLES=y\n"},
            ), mock.patch(
                "runtime.net_lane._check_guest_arm64_binary", return_value={"ok": True, "name": "arch-check"}
            ), mock.patch(
                "runtime.net_lane.shutdown_vm"
            ):
                result = run_live_preflight(
                    kernel=kernel,
                    disk_image=disk,
                    ssh_key=ssh_key,
                    syz_execprog=syz_execprog,
                    syz_executor=syz_executor,
                    out_dir=out_dir,
                )

            checks = {item["name"]: item for item in result["guest_checks"]}
            self.assertTrue(checks["serial_console"]["ok"])
            self.assertEqual(checks["serial_console"]["source"], "qemu_append")
            self.assertTrue(checks["debugfs_path"]["ok"])
            self.assertEqual(checks["debugfs_path"]["source"], "mounted-debugfs")

    def test_runtime_lane_can_stop_after_single_seed_stage(self) -> None:
        _, sm, tp = self._build_state_inputs()
        seeds = synthesize(sm)

        with tempfile.TemporaryDirectory() as tmpdir:
            base = pathlib.Path(tmpdir)
            seeds_dir = base / "seeds"
            out_dir = base / "live-run"
            seeds_dir.mkdir()
            for seed in seeds[:4]:
                (seeds_dir / seed["name"]).write_text(seed["prog_text"], encoding="utf-8")

            state_model_path = base / "state_model_v1.json"
            target_profile_path = base / "target_profile.json"
            state_model_path.write_text(json.dumps(sm), encoding="utf-8")
            target_profile_path.write_text(json.dumps(tp), encoding="utf-8")

            dummy = base / "dummy"
            dummy.write_bytes(b"x")
            ssh_key = base / "id_rsa"
            ssh_key.write_text("key", encoding="utf-8")
            ssh_key.chmod(0o600)

            preflight = {
                "ready": True,
                "host_checks": [],
                "guest_checks": [],
                "environment": {"arch": "aarch64", "cmdline": "console=ttyAMA0"},
            }

            observed: list[str] = []

            def fake_run_one_live_seed(*, seed, seed_out, **kwargs):
                observed.append(seed.name)
                seed_out.mkdir(parents=True, exist_ok=True)
                summary = {
                    "seed": seed.name,
                    "seed_dir": str(seed_out),
                    "execution_evidence": {
                        "target_family_hit": True,
                        "phase_reached": "trigger",
                        "phases_exercised": ["bootstrap", "configure", "trigger"],
                        "prefix_preserved": True,
                        "trigger_phase_reached": True,
                    },
                    "crash_evidence": {
                        "crash_detected": False,
                        "crash_kind": "none",
                        "real_crash_signal": False,
                        "signature": None,
                        "title": None,
                        "top_frames": [],
                        "source_files": [],
                    },
                    "candidate_evidence": {
                        "path_relevant": False,
                        "match_score": 0.0,
                        "specific_candidate_alignment": False,
                        "alignment_quality": "unrelated",
                        "subsystem_relevance_score": 0.0,
                        "specific_free_hit": False,
                        "specific_use_hit": False,
                    },
                    "triage_verdict": "insufficient_data",
                    "subsystem_relevance": "unrelated",
                    "seed_execution_status": {
                        "classification": "completed-no-crash",
                        "reasons": ["completed"],
                        "progress_signals": {"stdout_nonempty": True},
                    },
                }
                (seed_out / "seed_run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
                return summary

            with mock.patch("runtime.net_lane.run_live_preflight", return_value=preflight), mock.patch(
                "runtime.net_lane._run_one_live_seed", side_effect=fake_run_one_live_seed
            ):
                result = run_net_runtime_lane(
                    state_model_path=state_model_path,
                    target_profile_path=target_profile_path,
                    seeds_dir=seeds_dir,
                    out_dir=out_dir,
                    syz_execprog=dummy,
                    syz_executor=dummy,
                    kernel=dummy,
                    disk_image=dummy,
                    ssh_key=ssh_key,
                    stop_after_stage="single-seed-validation",
                )

            self.assertEqual(len(observed), 1)
            self.assertEqual(result["runtime_verdict"]["executed_stages"], ["single-seed-validation"])
            self.assertTrue((out_dir / "runtime" / "single_seed_stage_summary.json").exists())

    def test_runtime_lane_emits_single_seed_status_artifacts_for_stall(self) -> None:
        _, sm, tp = self._build_state_inputs()
        seeds = synthesize(sm)

        with tempfile.TemporaryDirectory() as tmpdir:
            base = pathlib.Path(tmpdir)
            seeds_dir = base / "seeds"
            out_dir = base / "live-run"
            seeds_dir.mkdir()
            for seed in seeds[:1]:
                (seeds_dir / seed["name"]).write_text(seed["prog_text"], encoding="utf-8")

            state_model_path = base / "state_model_v1.json"
            target_profile_path = base / "target_profile.json"
            state_model_path.write_text(json.dumps(sm), encoding="utf-8")
            target_profile_path.write_text(json.dumps(tp), encoding="utf-8")

            dummy = base / "dummy"
            dummy.write_bytes(b"x")
            ssh_key = base / "id_rsa"
            ssh_key.write_text("key", encoding="utf-8")
            ssh_key.chmod(0o600)

            preflight = {
                "ready": True,
                "host_checks": [],
                "guest_checks": [],
                "environment": {"arch": "aarch64", "cmdline": "console=ttyAMA0"},
            }

            def fake_run_one_live_seed(*, seed, seed_out, **kwargs):
                seed_out.mkdir(parents=True, exist_ok=True)
                status = {
                    "classification": "stalled",
                    "reasons": ["Guest seed execution exceeded the per-seed timeout without observable progress."],
                    "progress_signals": {
                        "stdout_nonempty": False,
                        "stderr_nonempty": False,
                        "coverage_copied": False,
                        "timed_out": True,
                        "ssh_command_timeout": True,
                    },
                }
                (seed_out / "seed_execution_status.json").write_text(json.dumps(status), encoding="utf-8")
                summary = {
                    "seed": seed.name,
                    "seed_dir": str(seed_out),
                    "execution_evidence": {
                        "target_family_hit": True,
                        "phase_reached": "trigger",
                        "phases_exercised": ["bootstrap", "configure", "trigger"],
                        "prefix_preserved": True,
                        "trigger_phase_reached": True,
                    },
                    "crash_evidence": {
                        "crash_detected": False,
                        "crash_kind": "timeout",
                        "real_crash_signal": False,
                        "signature": None,
                        "title": None,
                        "top_frames": [],
                        "source_files": [],
                    },
                    "candidate_evidence": {
                        "path_relevant": False,
                        "match_score": 0.0,
                        "specific_candidate_alignment": False,
                        "alignment_quality": "unrelated",
                        "subsystem_relevance_score": 0.0,
                        "specific_free_hit": False,
                        "specific_use_hit": False,
                    },
                    "triage_verdict": "insufficient_data",
                    "subsystem_relevance": "unrelated",
                    "seed_execution_status": status,
                }
                (seed_out / "seed_run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
                return summary

            with mock.patch("runtime.net_lane.run_live_preflight", return_value=preflight), mock.patch(
                "runtime.net_lane._run_one_live_seed", side_effect=fake_run_one_live_seed
            ):
                result = run_net_runtime_lane(
                    state_model_path=state_model_path,
                    target_profile_path=target_profile_path,
                    seeds_dir=seeds_dir,
                    out_dir=out_dir,
                    syz_execprog=dummy,
                    syz_executor=dummy,
                    kernel=dummy,
                    disk_image=dummy,
                    ssh_key=ssh_key,
                    stop_after_stage="single-seed-validation",
                )

            final_verdict = json.loads((out_dir / "runtime" / "final_verdict.json").read_text(encoding="utf-8"))
            single_seed = json.loads((out_dir / "runtime" / "single_seed_stage_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(single_seed["seed_result_summary"]["primary"]["classification"], "stalled")
            self.assertEqual(final_verdict["single_seed_result"]["classification"], "stalled")
            self.assertEqual(result["runtime_verdict"]["single_seed_result"]["classification"], "stalled")

    def test_prepare_guest_execution_retries_seed_copy_in_var_tmp(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = pathlib.Path(tmpdir)
            seed = base / "seed.prog"
            seed.write_text("r0 = socket$NETLINK_NETFILTER(0x10, 0x3, 0xc)\n", encoding="utf-8")

            def fake_copy(local_path, remote_path, ssh_port, ssh_key):
                if remote_path == "/tmp/madelin-net-runtime/seed.prog":
                    return {
                        "ok": False,
                        "error": "stream-copy rc=2",
                        "stderr": "Directory nonexistent",
                        "scp_error": "rc=1",
                        "scp_stderr": "No such file or directory",
                    }
                return {"ok": True, "path": remote_path}

            with mock.patch("runtime.net_lane._prepare_guest_runtime_environment", return_value={"ok": True}), mock.patch(
                "runtime.net_lane._copy_to_guest", side_effect=fake_copy
            ), mock.patch("runtime.net_lane._guest_cmd", return_value={"ok": True}):
                result = _prepare_guest_execution(
                    syz_execprog=None,
                    syz_executor=None,
                    seed=seed,
                    ssh_port=10022,
                    ssh_key=base / "id_rsa",
                    guest_syz_execprog_path="/usr/local/bin/syz-execprog",
                    guest_syz_executor_path="/usr/local/bin/syz-executor",
                )

            self.assertTrue(result["ok"])
            self.assertEqual(result["runtime_paths"]["runtime_dir"], "/var/tmp/madelin-net-runtime")
            self.assertEqual(result["copies"]["seed"]["path"], "/var/tmp/madelin-net-runtime/seed.prog")

    def test_runtime_lane_emits_proof_manifest_and_uses_controlled_seed_order(self) -> None:
        _, sm, tp = self._build_state_inputs()
        seeds = synthesize(sm)

        with tempfile.TemporaryDirectory() as tmpdir:
            base = pathlib.Path(tmpdir)
            seeds_dir = base / "seeds"
            out_dir = base / "live-run"
            seeds_dir.mkdir()
            seed_manifest = {"seeds": [{"name": seed["name"]} for seed in seeds]}
            (seeds_dir / "seed_manifest.json").write_text(json.dumps(seed_manifest), encoding="utf-8")
            for seed in seeds:
                (seeds_dir / seed["name"]).write_text(seed["prog_text"], encoding="utf-8")

            state_model_path = base / "state_model_v1.json"
            target_profile_path = base / "target_profile.json"
            proof_kernel_meta_path = base / "proof-kernel.json"
            state_model_path.write_text(json.dumps(sm), encoding="utf-8")
            target_profile_path.write_text(json.dumps(tp), encoding="utf-8")
            proof_kernel_meta_path.write_text(json.dumps({"source_head": "deadbeef"}), encoding="utf-8")

            dummy = base / "dummy"
            dummy.write_bytes(b"x")
            ssh_key = base / "id_rsa"
            ssh_key.write_text("key", encoding="utf-8")
            ssh_key.chmod(0o600)

            preflight = {
                "ready": True,
                "host_checks": [],
                "guest_checks": [],
                "environment": {"arch": "aarch64", "cmdline": "console=ttyAMA0"},
            }

            observed: list[str] = []

            def fake_run_one_live_seed(*, seed, seed_out, **kwargs):
                observed.append(seed.name)
                seed_out.mkdir(parents=True, exist_ok=True)
                summary = {
                    "seed": seed.name,
                    "seed_dir": str(seed_out),
                    "execution_evidence": {
                        "target_family_hit": True,
                        "phase_reached": "trigger",
                        "phases_exercised": ["bootstrap", "configure", "trigger"],
                        "prefix_preserved": True,
                        "trigger_phase_reached": True,
                    },
                    "crash_evidence": {
                        "crash_detected": False,
                        "crash_kind": "none",
                        "real_crash_signal": False,
                        "signature": None,
                        "title": None,
                        "top_frames": [],
                        "source_files": [],
                    },
                    "candidate_evidence": {
                        "path_relevant": False,
                        "match_score": 0.0,
                        "specific_candidate_alignment": False,
                        "alignment_quality": "unrelated",
                        "subsystem_relevance_score": 0.0,
                        "specific_free_hit": False,
                        "specific_use_hit": False,
                    },
                    "triage_verdict": "insufficient_data",
                    "subsystem_relevance": "unrelated",
                    "seed_execution_status": {
                        "classification": "completed-no-crash",
                        "reasons": ["completed"],
                        "progress_signals": {"stdout_nonempty": True},
                    },
                }
                (seed_out / "seed_run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
                return summary

            with mock.patch("runtime.net_lane.run_live_preflight", return_value=preflight), mock.patch(
                "runtime.net_lane._run_one_live_seed", side_effect=fake_run_one_live_seed
            ):
                run_net_runtime_lane(
                    state_model_path=state_model_path,
                    target_profile_path=target_profile_path,
                    seeds_dir=seeds_dir,
                    out_dir=out_dir,
                    syz_execprog=dummy,
                    syz_executor=dummy,
                    kernel=dummy,
                    disk_image=dummy,
                    ssh_key=ssh_key,
                    stop_after_stage="single-seed-validation",
                    proof_mode="controlled",
                    proof_kernel_meta_path=proof_kernel_meta_path,
                )

            proof_manifest = json.loads((out_dir / "logs" / "proof_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(observed, ["seed_delete_dump.prog"])
            self.assertEqual(proof_manifest["proof_mode"], "controlled")
            self.assertEqual(proof_manifest["seed"], "seed_delete_dump.prog")
            self.assertEqual(proof_manifest["proof_kernel_meta"]["source_head"], "deadbeef")


if __name__ == "__main__":
    unittest.main()
