#!/usr/bin/env python3
"""Backend dry-run proofs for target packs."""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from orchestrator.campaign import Campaign
from schemas import validate as schema_validate
from seedgen.synthesize_seeds import emit_manifest, synthesize
from state_model.build_state_model import build_relation_graph, build_state_model, build_target_profile
from triage.report import build_triage_report

_FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

_PACK_CRASH_CASES = {
    "io_uring": {
        "use_frame": "__io_submit_flush_completions",
        "free_frame": "io_ring_ctx_free",
        "file": "io_uring/io_uring.c",
    },
    "net": {
        "use_frame": "nf_tables_dump_set",
        "free_frame": "nf_tables_destroy_set",
        "file": "net/netfilter/nf_tables_api.c",
    },
    "bpf": {
        "use_frame": "bpf_map_lookup_elem",
        "free_frame": "bpf_link_free",
        "file": "kernel/bpf/syscall.c",
    },
    "fs": {
        "use_frame": "vfs_get_tree",
        "free_frame": "put_fs_context",
        "file": "fs/fs_context.c",
    },
}


def _load_json(path: pathlib.Path) -> dict:
    with open(path) as f:
        return json.load(f)


class TestPackFixtures(unittest.TestCase):
    def _synthetic_kasan_report(self, pack_name: str) -> str:
        case = _PACK_CRASH_CASES[pack_name]
        return f"""
BUG: KASAN: use-after-free in {case['use_frame']}+0x1a/0x30 {case['file']}:123
Read of size 8 at addr ffff0000deadbeef by task syz-executor/1234

Call Trace:
 {case['use_frame']}+0x1a/0x30
 some_helper+0x4e/0x90

Freed by task 1232:
 {case['free_frame']}+0x56/0x78
"""

    def _assert_artifacts_valid(self, candidate: dict, plan: dict, pack_name: str) -> None:
        sm = build_state_model(candidate, plan, f"fixtures/packs/{pack_name}/candidate.json", f"fixtures/packs/{pack_name}/witness_plan.json")
        tp = build_target_profile(candidate)
        rg = build_relation_graph(candidate, plan, sm)

        self.assertEqual(schema_validate(sm, "state_model_v1"), [], f"{pack_name}: state_model schema errors")
        self.assertEqual(schema_validate(tp, "target_profile"), [], f"{pack_name}: target_profile schema errors")
        self.assertEqual(schema_validate(rg, "relation_graph_v1"), [], f"{pack_name}: relation_graph schema errors")

        self.assertEqual(sm["candidate_id"], candidate["candidate_id"])
        self.assertEqual(tp["candidate_id"], candidate["candidate_id"])
        self.assertGreaterEqual(len(sm["phases"]["bootstrap"]["calls"]), 1, f"{pack_name}: empty bootstrap phase")

        seeds = synthesize(sm)
        self.assertGreater(len(seeds), 0, f"{pack_name}: no seeds synthesized")
        for seed in seeds:
            self.assertIn("prog_text", seed)
            self.assertGreater(len(seed["prog_text"]), 0)
            self.assertNotIn("UNSUPPORTED", seed["prog_text"], f"{pack_name}: unexpected UNSUPPORTED marker")

        manifest = emit_manifest(seeds, sm)
        self.assertEqual(manifest["seed_count"], len(seeds))
        self.assertEqual(manifest["candidate_id"], candidate["candidate_id"])

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = pathlib.Path(tmpdir)
            seeds_dir = tmpdir_path / "seeds"
            work_dir = tmpdir_path / "campaign"
            seeds_dir.mkdir()

            for seed in seeds:
                (seeds_dir / seed["name"]).write_text(seed["prog_text"], encoding="utf-8")

            campaign = Campaign(
                state_model=sm,
                target_profile=tp,
                relation_graph=rg,
                work_dir=work_dir,
                max_iterations=6,
            )
            seed_count = campaign.import_seeds(seeds_dir)
            self.assertEqual(seed_count, len(seeds), f"{pack_name}: campaign import count mismatch")
            summary = campaign.run()
            campaign.save_artifacts()

            self.assertGreaterEqual(summary["iterations"], 1, f"{pack_name}: no campaign iterations")
            self.assertTrue((work_dir / "campaign_summary.json").exists(), f"{pack_name}: missing campaign summary")

        calls = sm["phases"]["bootstrap"]["calls"] + sm["phases"]["configure"]["calls"] + sm["phases"]["trigger"]["calls"]
        report = build_triage_report(self._synthetic_kasan_report(pack_name), tp, sm, calls)
        self.assertEqual(schema_validate(report, "triage_report_v1"), [], f"{pack_name}: triage schema errors")
        self.assertIn(report["verdict"], {"plausible", "confirmed"}, f"{pack_name}: unexpected triage verdict")
        self.assertGreater(report["candidate_match"]["match_score"], 0.4, f"{pack_name}: weak triage match")

    def test_io_uring_pack_fixture(self) -> None:
        base = _FIXTURES / "packs" / "io_uring"
        self._assert_artifacts_valid(_load_json(base / "candidate.json"), _load_json(base / "witness_plan.json"), "io_uring")

    def test_net_pack_fixture(self) -> None:
        base = _FIXTURES / "packs" / "net"
        self._assert_artifacts_valid(_load_json(base / "candidate.json"), _load_json(base / "witness_plan.json"), "net")

    def test_bpf_pack_fixture(self) -> None:
        base = _FIXTURES / "packs" / "bpf"
        self._assert_artifacts_valid(_load_json(base / "candidate.json"), _load_json(base / "witness_plan.json"), "bpf")

    def test_fs_pack_fixture(self) -> None:
        base = _FIXTURES / "packs" / "fs"
        self._assert_artifacts_valid(_load_json(base / "candidate.json"), _load_json(base / "witness_plan.json"), "fs")


if __name__ == "__main__":
    unittest.main()
