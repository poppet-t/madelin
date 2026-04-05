#!/usr/bin/env python3
"""Tests for io_uring-specific triage symbol enrichment."""

from __future__ import annotations

import pathlib
import sys
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from triage.io_uring_symbols import (
    IO_URING_LIFECYCLE_FUNCTIONS,
    IO_URING_SOURCE_FILES,
    IO_URING_TEARDOWN_FUNCTIONS,
    IO_URING_USE_FUNCTIONS,
    classify_crash_subsystem_relevance,
    enrich_crash_match,
)


class TestSymbolTables(unittest.TestCase):
    def test_lifecycle_contains_core_functions(self) -> None:
        for func in ["io_uring_setup", "io_uring_enter", "io_ring_ctx_free", "io_uring_release"]:
            self.assertIn(func, IO_URING_LIFECYCLE_FUNCTIONS)

    def test_teardown_is_subset_of_lifecycle(self) -> None:
        self.assertTrue(IO_URING_TEARDOWN_FUNCTIONS <= IO_URING_LIFECYCLE_FUNCTIONS)

    def test_use_is_subset_of_lifecycle(self) -> None:
        self.assertTrue(IO_URING_USE_FUNCTIONS <= IO_URING_LIFECYCLE_FUNCTIONS)

    def test_source_files_contain_primary(self) -> None:
        self.assertIn("io_uring/io_uring.c", IO_URING_SOURCE_FILES)
        self.assertIn("fs/io_uring.c", IO_URING_SOURCE_FILES)


class TestEnrichCrashMatch(unittest.TestCase):
    def _base_match(self) -> dict:
        return {
            "focus_frame_hit": True,
            "focus_file_hit": True,
            "free_use_hint_match": True,
            "uaf_type_match": True,
            "match_score": 0.85,
        }

    def test_enrichment_adds_io_uring_fields(self) -> None:
        crash = {
            "stack_frames": ["io_ring_ctx_free", "__do_sys_io_uring_enter"],
            "source_files": ["io_uring/io_uring.c"],
        }
        enriched = enrich_crash_match(crash, self._base_match())
        self.assertIn("io_uring_enrichment", enriched)
        e = enriched["io_uring_enrichment"]
        self.assertTrue(e["is_io_uring_crash"])
        self.assertTrue(e["has_teardown_use_pair"])
        self.assertGreater(e["subsystem_relevance_score"], 0.5)

    def test_enrichment_no_io_uring_frames(self) -> None:
        crash = {
            "stack_frames": ["some_random_function", "another_function"],
            "source_files": ["net/core/sock.c"],
        }
        enriched = enrich_crash_match(crash, self._base_match())
        e = enriched["io_uring_enrichment"]
        self.assertFalse(e["is_io_uring_crash"])
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
            "source_files": ["io_uring/io_uring.c", "io_uring/rsrc.c"],
        }
        enriched = enrich_crash_match(crash, self._base_match())
        e = enriched["io_uring_enrichment"]
        self.assertTrue(e["is_io_uring_crash"])
        self.assertGreater(e["subsystem_relevance_score"], 0.0)
        self.assertFalse(e["has_teardown_use_pair"])

    def test_enrichment_teardown_only(self) -> None:
        crash = {
            "stack_frames": ["io_ring_ctx_free", "io_uring_release"],
            "source_files": [],
        }
        enriched = enrich_crash_match(crash, self._base_match())
        e = enriched["io_uring_enrichment"]
        self.assertTrue(e["is_io_uring_crash"])
        self.assertGreater(len(e["teardown_frame_hits"]), 0)
        self.assertEqual(len(e["use_frame_hits"]), 0)
        self.assertFalse(e["has_teardown_use_pair"])


class TestClassifyCrashSubsystemRelevance(unittest.TestCase):
    def test_teardown_use(self) -> None:
        crash = {
            "stack_frames": ["io_ring_ctx_free", "__do_sys_io_uring_enter"],
            "source_files": [],
        }
        self.assertEqual(classify_crash_subsystem_relevance(crash), "io_uring_teardown_use")

    def test_lifecycle_only(self) -> None:
        crash = {
            "stack_frames": ["io_uring_setup", "io_sq_offload_create"],
            "source_files": [],
        }
        self.assertEqual(classify_crash_subsystem_relevance(crash), "io_uring_lifecycle")

    def test_file_only(self) -> None:
        crash = {
            "stack_frames": ["unknown_func"],
            "source_files": ["io_uring/io_uring.c"],
        }
        self.assertEqual(classify_crash_subsystem_relevance(crash), "io_uring_file_only")

    def test_unrelated(self) -> None:
        crash = {
            "stack_frames": ["sock_sendmsg", "inet_sendmsg"],
            "source_files": ["net/core/sock.c"],
        }
        self.assertEqual(classify_crash_subsystem_relevance(crash), "unrelated")


if __name__ == "__main__":
    unittest.main()
