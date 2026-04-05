#!/usr/bin/env python3

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from runtime.net_lab import (
    build_blocker_report,
    build_kernel_provenance,
    build_lab_run_bundle,
    build_source_frame_summary,
    classify_lab_net_state,
    rank_net_files,
    rank_net_seeds,
)


class TestNetLabHelpers(unittest.TestCase):
    def test_rank_net_files_is_deterministic(self) -> None:
        target_profile = {
            "focus_files": ["net/netfilter/nf_tables_api.c"],
            "free_use_hints": [
                {"role": "free", "function": "nf_tables_destroy_set", "file": "net/netfilter/nf_tables_api.c"},
                {"role": "use", "function": "nf_tables_dump_set", "file": "net/netfilter/nf_tables_api.c"},
            ],
        }
        manifest = {"kernel_area_prefixes": ["net/netfilter", "net/netlink"]}
        result = rank_net_files(candidate={"candidate_id": "cand"}, target_profile=target_profile, manifest=manifest)
        self.assertEqual(result["ranked_files"][0]["path"], "net/netfilter/nf_tables_api.c")
        self.assertIn("target profile focus file", result["ranked_files"][0]["reasons"])

    def test_rank_net_seeds_prefers_controlled_proof_seed(self) -> None:
        result = rank_net_seeds(
            seed_manifest={
                "seeds": [
                    {"name": "seed_dump_delete.prog", "call_count": 4},
                    {"name": "seed_delete_dump.prog", "call_count": 4},
                ]
            },
            target_profile={"focus_files": [], "free_use_hints": []},
            candidate={"candidate_id": "cand"},
            proof_mode="controlled",
        )
        self.assertEqual(result["ranked_seeds"][0]["seed"], "seed_delete_dump.prog")

    def test_source_frame_summary_tracks_expected_pair(self) -> None:
        summary = build_source_frame_summary(
            crash_evidence_summary={
                "title": "BUG: KASAN: use-after-free in nf_tables_dump_set",
                "signature": "deadbeef",
                "top_frames": ["nf_tables_dump_set", "nf_tables_destroy_set"],
                "source_files": ["net/netfilter/nf_tables_api.c"],
            },
            candidate_evidence_summary={"specific_candidate_alignment": True, "path_relevant": True},
            target_profile={
                "free_use_hints": [
                    {"role": "free", "function": "nf_tables_destroy_set"},
                    {"role": "use", "function": "nf_tables_dump_set"},
                ]
            },
            reproducibility_summary={"classification": "reproducible crash"},
        )
        self.assertTrue(summary["exact_expected_pair_observed"])

    def test_blocker_report_for_guest_exec_failure(self) -> None:
        report = build_blocker_report(
            runtime_verdict={"verdict_class": "target reached, no crash", "reasons": ["x"]},
            single_seed_result={"classification": "guest-exec-failure"},
            preflight_summary_path=pathlib.Path("/tmp/preflight_summary.json"),
            seed_dir=pathlib.Path("/tmp/seed"),
        )
        self.assertEqual(report["failure_class"], "guest-exec-failure")
        self.assertIn("syz-execprog stdout/stderr", report["recommended_next_step"])

    def test_lab_state_requires_exact_source_frames(self) -> None:
        result = classify_lab_net_state(
            runtime_verdict={
                "verdict_class": "novelty-unchecked bug candidate",
                "real_crash_bar": {
                    "real_crash_signal": True,
                    "reproduced_at_least_twice": True,
                    "nf_tables_relevant": True,
                    "prefix_and_lifecycle_preserved": True,
                    "specific_candidate_alignment": True,
                },
            },
            source_frame_summary={"exact_expected_pair_observed": True},
            reproducibility_summary={"classification": "reproducible crash"},
            lab_context={"lab_only": True},
        )
        self.assertEqual(result["lab_state"], "patch candidate for reproduced lab bug")

    def test_build_lab_run_bundle_includes_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = pathlib.Path(tmpdir)
            seed_dir = out_dir / "runtime" / "single-seed-validation" / "01-seed"
            seed_dir.mkdir(parents=True)
            bundle = build_lab_run_bundle(
                kernel_provenance={"kernel_image_path": "/tmp/Image"},
                source_frame_summary={"exact_expected_pair_observed": False},
                runtime_verdict={"verdict_class": "target reached, no crash"},
                lab_state={"lab_state": "no bug confirmed; exact blocker"},
                blocker_report={"failure_class": "completed-no-crash"},
                guest_environment_summary={"guest_syz_execprog_path": "/usr/local/bin/syz-execprog"},
                single_seed_result={"seed": "seed_delete_dump.prog"},
                seed_dir=seed_dir,
                out_dir=out_dir,
            )
        self.assertTrue(bundle["seed_path"].endswith("seed_delete_dump.prog"))
        self.assertEqual(bundle["guest_tool_paths"]["syz_execprog"], "/usr/local/bin/syz-execprog")

    def test_build_kernel_provenance_hashes_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = pathlib.Path(tmpdir)
            kernel = base / "Image"
            disk = base / "disk.qcow2"
            kernel.write_bytes(b"kernel")
            disk.write_bytes(b"disk")
            provenance = build_kernel_provenance(
                kernel=kernel,
                disk_image=disk,
                preflight_environment={"kernel_config_path": "/proc/config.gz", "kernel_config_present": ["CONFIG_KASAN=y"]},
                proof_kernel_meta={"source_head": "deadbeef"},
            )
        self.assertEqual(provenance["kernel_config_path"], "/proc/config.gz")
        self.assertIsNotNone(provenance["kernel_image_sha256"])


if __name__ == "__main__":
    unittest.main()
