#!/usr/bin/env python3
"""Tests for net-specific triage symbol enrichment."""

from __future__ import annotations

import pathlib
import sys
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from triage.net_symbols import (
    NET_LIFECYCLE_FUNCTIONS,
    NET_SOURCE_FILES,
    NET_TEARDOWN_FUNCTIONS,
    NET_USE_FUNCTIONS,
    classify_crash_subsystem_relevance,
    enrich_crash_match,
)


class TestSymbolTables(unittest.TestCase):
    def test_lifecycle_contains_core_functions(self) -> None:
        for func in ["nfnetlink_rcv_batch", "nf_tables_newset", "nf_tables_destroy_set", "nf_tables_dump_set"]:
            self.assertIn(func, NET_LIFECYCLE_FUNCTIONS)

    def test_teardown_is_subset_of_lifecycle(self) -> None:
        self.assertTrue(NET_TEARDOWN_FUNCTIONS <= NET_LIFECYCLE_FUNCTIONS)

    def test_use_is_subset_of_lifecycle(self) -> None:
        self.assertTrue(NET_USE_FUNCTIONS <= NET_LIFECYCLE_FUNCTIONS)

    def test_source_files_contain_primary(self) -> None:
        self.assertIn("net/netfilter/nf_tables_api.c", NET_SOURCE_FILES)
        self.assertIn("net/netlink/af_netlink.c", NET_SOURCE_FILES)


class TestEnrichCrashMatch(unittest.TestCase):
    def _base_match(self) -> dict:
        return {
            "focus_frame_hit": True,
            "focus_file_hit": True,
            "free_use_hint_match": True,
            "uaf_type_match": True,
            "match_score": 0.85,
        }

    def test_enrichment_adds_net_fields(self) -> None:
        crash = {
            "stack_frames": ["nf_tables_destroy_set", "nf_tables_dump_set"],
            "source_files": ["net/netfilter/nf_tables_api.c"],
        }
        enriched = enrich_crash_match(crash, self._base_match())
        self.assertIn("net_enrichment", enriched)
        e = enriched["net_enrichment"]
        self.assertTrue(e["is_net_crash"])
        self.assertTrue(e["has_teardown_use_pair"])
        self.assertGreater(e["subsystem_relevance_score"], 0.5)

    def test_enrichment_no_net_frames(self) -> None:
        crash = {
            "stack_frames": ["some_random_function", "another_function"],
            "source_files": ["fs/ext4/super.c"],
        }
        enriched = enrich_crash_match(crash, self._base_match())
        e = enriched["net_enrichment"]
        self.assertFalse(e["is_net_crash"])
        self.assertEqual(e["subsystem_relevance_score"], 0.0)
        self.assertFalse(e["has_teardown_use_pair"])

    def test_enrichment_preserves_base_fields(self) -> None:
        crash = {"stack_frames": [], "source_files": []}
        base = self._base_match()
        enriched = enrich_crash_match(crash, base)
        for key in base:
            self.assertEqual(enriched[key], base[key])

    def test_enrichment_file_only(self) -> None:
        crash = {
            "stack_frames": ["unknown_function"],
            "source_files": ["net/netfilter/nf_tables_api.c", "net/netlink/af_netlink.c"],
        }
        enriched = enrich_crash_match(crash, self._base_match())
        e = enriched["net_enrichment"]
        self.assertTrue(e["is_net_crash"])
        self.assertGreater(e["subsystem_relevance_score"], 0.0)
        self.assertFalse(e["has_teardown_use_pair"])

    def test_enrichment_teardown_only(self) -> None:
        crash = {
            "stack_frames": ["nf_tables_destroy_set", "nf_tables_delset"],
            "source_files": [],
        }
        enriched = enrich_crash_match(crash, self._base_match())
        e = enriched["net_enrichment"]
        self.assertTrue(e["is_net_crash"])
        self.assertGreater(len(e["teardown_frame_hits"]), 0)
        self.assertEqual(len(e["use_frame_hits"]), 0)
        self.assertFalse(e["has_teardown_use_pair"])


class TestClassifyCrashSubsystemRelevance(unittest.TestCase):
    def test_teardown_use(self) -> None:
        crash = {
            "stack_frames": ["nf_tables_destroy_set", "nf_tables_dump_set"],
            "source_files": [],
        }
        self.assertEqual(classify_crash_subsystem_relevance(crash), "net_teardown_use")

    def test_lifecycle_only(self) -> None:
        crash = {
            "stack_frames": ["nf_tables_newset", "nfnetlink_rcv_batch"],
            "source_files": [],
        }
        self.assertEqual(classify_crash_subsystem_relevance(crash), "net_lifecycle")

    def test_file_only(self) -> None:
        crash = {
            "stack_frames": ["unknown_func"],
            "source_files": ["net/netfilter/nf_tables_api.c"],
        }
        self.assertEqual(classify_crash_subsystem_relevance(crash), "net_file_only")

    def test_unrelated(self) -> None:
        crash = {
            "stack_frames": ["io_uring_setup", "io_ring_ctx_alloc"],
            "source_files": ["io_uring/io_uring.c"],
        }
        self.assertEqual(classify_crash_subsystem_relevance(crash), "unrelated")


if __name__ == "__main__":
    unittest.main()
