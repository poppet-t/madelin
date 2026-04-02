#!/usr/bin/env python3
"""Backend-only dry-run proofs for non-KVM packs.

These tests do not execute syzkaller or a real kernel. They prove that the backend can
consume bridge artifacts and emit runtime artifacts + seeds deterministically.
"""

from __future__ import annotations

import json
import pathlib
import sys
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from schemas import validate as schema_validate
from seedgen.synthesize_seeds import synthesize
from state_model.build_state_model import build_state_model, build_target_profile, build_relation_graph

_FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def _load_json(path: pathlib.Path) -> dict:
    with open(path) as f:
        return json.load(f)


class TestPackFixtures(unittest.TestCase):
    def _assert_artifacts_valid(self, candidate: dict, plan: dict, pack_name: str) -> None:
        sm = build_state_model(candidate, plan, f"fixtures/packs/{pack_name}/candidate.json", f"fixtures/packs/{pack_name}/witness_plan.json")
        tp = build_target_profile(candidate)
        rg = build_relation_graph(candidate, plan, sm)

        self.assertEqual(schema_validate(sm, "state_model_v1"), [], f"{pack_name}: state_model schema errors")
        self.assertEqual(schema_validate(tp, "target_profile"), [], f"{pack_name}: target_profile schema errors")
        self.assertEqual(schema_validate(rg, "relation_graph_v1"), [], f"{pack_name}: relation_graph schema errors")

        # Basic expectations: non-empty bootstrap, stable IDs.
        self.assertEqual(sm["candidate_id"], candidate["candidate_id"])
        self.assertEqual(tp["candidate_id"], candidate["candidate_id"])
        self.assertGreaterEqual(len(sm["phases"]["bootstrap"]["calls"]), 1, f"{pack_name}: empty bootstrap phase")

        seeds = synthesize(sm)
        self.assertGreater(len(seeds), 0, f"{pack_name}: no seeds synthesized")
        for seed in seeds:
            self.assertIn("prog_text", seed)
            self.assertGreater(len(seed["prog_text"]), 0)
            self.assertNotIn("UNSUPPORTED", seed["prog_text"], f"{pack_name}: unexpected UNSUPPORTED marker")

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

