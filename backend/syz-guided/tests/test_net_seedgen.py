#!/usr/bin/env python3
"""Tests for net-specific seed synthesis and prefix preservation."""

from __future__ import annotations

import json
import pathlib
import sys
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from pack_registry import target_manifest
from seedgen.synthesize_seeds import emit_manifest, synthesize
from state_model.build_state_model import build_state_model, build_target_profile

_FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "packs" / "net"


def _load_json(path: pathlib.Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _build_net_state_model() -> dict:
    candidate = _load_json(_FIXTURES / "candidate.json")
    plan = _load_json(_FIXTURES / "witness_plan.json")
    return build_state_model(
        candidate, plan,
        "fixtures/packs/net/candidate.json",
        "fixtures/packs/net/witness_plan.json",
    )


class TestNetSeedgen(unittest.TestCase):
    def test_synthesizes_five_variants(self) -> None:
        sm = _build_net_state_model()
        seeds = synthesize(sm)
        self.assertEqual(len(seeds), 5)
        names = {seed["name"] for seed in seeds}
        self.assertEqual(names, {
            "seed_delete_dump.prog",
            "seed_dump_delete.prog",
            "seed_delete_close.prog",
            "seed_dump_close.prog",
            "seed_update_dump_delete.prog",
        })

    def test_bootstrap_prefix_preserved_in_all_seeds(self) -> None:
        sm = _build_net_state_model()
        bootstrap_calls = sm["phases"]["bootstrap"]["calls"]
        prefix_len = sm["immutable_prefix_len"]
        self.assertGreaterEqual(prefix_len, 1)
        self.assertEqual(bootstrap_calls, ["socket$NETLINK_NETFILTER"])

        seeds = synthesize(sm)
        for seed in seeds:
            calls = seed["calls"]
            self.assertGreaterEqual(len(calls), prefix_len,
                                    f"{seed['name']}: fewer calls than prefix length")
            for i in range(prefix_len):
                self.assertEqual(calls[i], bootstrap_calls[i],
                                 f"{seed['name']}: prefix call {i} mismatch: {calls[i]} != {bootstrap_calls[i]}")

    def test_configure_phase_after_bootstrap(self) -> None:
        sm = _build_net_state_model()
        seeds = synthesize(sm)
        bootstrap = sm["phases"]["bootstrap"]["calls"]
        configure = sm["phases"]["configure"]["calls"]
        prefix_len = len(bootstrap)

        for seed in seeds:
            calls = seed["calls"]
            for i, cfg_call in enumerate(configure):
                expected_pos = prefix_len + i
                self.assertEqual(calls[expected_pos], cfg_call,
                                 f"{seed['name']}: configure call {i} at wrong position")

    def test_suffix_varies_across_variants(self) -> None:
        sm = _build_net_state_model()
        seeds = synthesize(sm)
        bootstrap = sm["phases"]["bootstrap"]["calls"]
        configure = sm["phases"]["configure"]["calls"]
        prefix = bootstrap + configure

        suffixes = set()
        for seed in seeds:
            suffix = tuple(seed["calls"][len(prefix):])
            suffixes.add(suffix)
        self.assertGreater(len(suffixes), 1, "All seeds have identical suffixes")

    def test_prog_text_contains_syz_calls(self) -> None:
        sm = _build_net_state_model()
        seeds = synthesize(sm)
        for seed in seeds:
            text = seed["prog_text"]
            self.assertIn("socket$NETLINK_NETFILTER", text)
            self.assertIn("candidate:", text)
            self.assertIn("immutable_prefix:", text)

    def test_manifest_matches_seeds(self) -> None:
        sm = _build_net_state_model()
        seeds = synthesize(sm)
        manifest = emit_manifest(seeds, sm)
        self.assertEqual(manifest["seed_count"], 5)
        self.assertEqual(manifest["candidate_id"], sm["candidate_id"])
        self.assertEqual(manifest["immutable_prefix_len"], sm["immutable_prefix_len"])

    def test_delete_dump_variant_preserves_candidate_order(self) -> None:
        sm = _build_net_state_model()
        seeds = synthesize(sm)
        delete_dump = [s for s in seeds if s["name"] == "seed_delete_dump.prog"]
        self.assertEqual(len(delete_dump), 1)
        calls = delete_dump[0]["calls"]
        self.assertLess(calls.index("sendmsg$NFT_BATCH_DELETE"), calls.index("recvmsg$NETLINK_DUMP"))

    def test_resource_chain_in_all_seeds(self) -> None:
        sm = _build_net_state_model()
        seeds = synthesize(sm)
        for seed in seeds:
            calls = seed["calls"]
            self.assertIn("socket$NETLINK_NETFILTER", calls,
                          f"{seed['name']}: missing netlink socket setup (resource producer)")

    def test_dump_delete_variant_has_both(self) -> None:
        sm = _build_net_state_model()
        seeds = synthesize(sm)
        dump_delete = [s for s in seeds if s["name"] == "seed_dump_delete.prog"]
        self.assertEqual(len(dump_delete), 1)
        calls = dump_delete[0]["calls"]
        self.assertIn("recvmsg$NETLINK_DUMP", calls)
        self.assertIn("sendmsg$NFT_BATCH_DELETE", calls)

    def test_update_dump_delete_variant_has_all(self) -> None:
        sm = _build_net_state_model()
        seeds = synthesize(sm)
        udd = [s for s in seeds if s["name"] == "seed_update_dump_delete.prog"]
        self.assertEqual(len(udd), 1)
        calls = udd[0]["calls"]
        self.assertIn("sendmsg$NFT_BATCH_UPDATE", calls)
        self.assertIn("recvmsg$NETLINK_DUMP", calls)
        self.assertIn("sendmsg$NFT_BATCH_DELETE", calls)


if __name__ == "__main__":
    unittest.main()
