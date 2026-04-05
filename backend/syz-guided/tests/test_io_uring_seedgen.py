#!/usr/bin/env python3
"""Tests for io_uring-specific seed synthesis and prefix preservation."""

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

_FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "packs" / "io_uring"


def _load_json(path: pathlib.Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _build_io_uring_state_model() -> dict:
    candidate = _load_json(_FIXTURES / "candidate.json")
    plan = _load_json(_FIXTURES / "witness_plan.json")
    return build_state_model(
        candidate, plan,
        "fixtures/packs/io_uring/candidate.json",
        "fixtures/packs/io_uring/witness_plan.json",
    )


class TestIoUringSeedgen(unittest.TestCase):
    def test_synthesizes_four_variants(self) -> None:
        sm = _build_io_uring_state_model()
        seeds = synthesize(sm)
        self.assertEqual(len(seeds), 4)
        names = {seed["name"] for seed in seeds}
        self.assertEqual(names, {
            "seed_enter_once.prog",
            "seed_enter_close.prog",
            "seed_poll_close.prog",
            "seed_dup_enter.prog",
        })

    def test_bootstrap_prefix_preserved_in_all_seeds(self) -> None:
        sm = _build_io_uring_state_model()
        manifest = target_manifest("io_uring")
        bootstrap_calls = sm["phases"]["bootstrap"]["calls"]
        prefix_len = sm["immutable_prefix_len"]
        self.assertGreaterEqual(prefix_len, 1)
        self.assertEqual(bootstrap_calls, ["io_uring_setup"])

        seeds = synthesize(sm)
        for seed in seeds:
            calls = seed["calls"]
            self.assertGreaterEqual(len(calls), prefix_len,
                                    f"{seed['name']}: fewer calls than prefix length")
            for i in range(prefix_len):
                self.assertEqual(calls[i], bootstrap_calls[i],
                                 f"{seed['name']}: prefix call {i} mismatch: {calls[i]} != {bootstrap_calls[i]}")

    def test_configure_phase_after_bootstrap(self) -> None:
        sm = _build_io_uring_state_model()
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
        sm = _build_io_uring_state_model()
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
        sm = _build_io_uring_state_model()
        seeds = synthesize(sm)
        for seed in seeds:
            text = seed["prog_text"]
            self.assertIn("io_uring_setup", text)
            self.assertIn("candidate:", text)
            self.assertIn("immutable_prefix:", text)

    def test_manifest_matches_seeds(self) -> None:
        sm = _build_io_uring_state_model()
        seeds = synthesize(sm)
        manifest = emit_manifest(seeds, sm)
        self.assertEqual(manifest["seed_count"], 4)
        self.assertEqual(manifest["candidate_id"], sm["candidate_id"])
        self.assertEqual(manifest["immutable_prefix_len"], sm["immutable_prefix_len"])

    def test_resource_chain_in_all_seeds(self) -> None:
        sm = _build_io_uring_state_model()
        seeds = synthesize(sm)
        for seed in seeds:
            calls = seed["calls"]
            self.assertIn("io_uring_setup", calls,
                          f"{seed['name']}: missing ring setup (resource producer)")

    def test_enter_close_variant_has_both(self) -> None:
        sm = _build_io_uring_state_model()
        seeds = synthesize(sm)
        enter_close = [s for s in seeds if s["name"] == "seed_enter_close.prog"]
        self.assertEqual(len(enter_close), 1)
        calls = enter_close[0]["calls"]
        self.assertIn("io_uring_enter", calls)
        self.assertIn("close$io_uring", calls)

    def test_dup_enter_variant_has_dup(self) -> None:
        sm = _build_io_uring_state_model()
        seeds = synthesize(sm)
        dup_enter = [s for s in seeds if s["name"] == "seed_dup_enter.prog"]
        self.assertEqual(len(dup_enter), 1)
        calls = dup_enter[0]["calls"]
        self.assertIn("dup$io_uring", calls)
        self.assertIn("io_uring_enter", calls)


if __name__ == "__main__":
    unittest.main()
