#!/usr/bin/env python3

from __future__ import annotations

import pathlib
import sys
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from triage.net_verdict import (
    build_candidate_evidence,
    build_crash_evidence,
    build_execution_evidence,
    classify_net_lab_state,
    classify_net_runtime_verdict,
    classify_reproducibility,
)


class TestNetVerdictLayers(unittest.TestCase):
    def setUp(self) -> None:
        self.target_profile = {
            "free_use_hints": [
                {"role": "free", "function": "nf_tables_destroy_set", "file": "net/netfilter/nf_tables_api.c"},
                {"role": "use", "function": "nf_tables_dump_set", "file": "net/netfilter/nf_tables_api.c"},
            ]
        }

    def test_execution_evidence_tracks_prefix_and_trigger(self) -> None:
        evidence = build_execution_evidence(
            seed="seed.prog",
            calls=[
                "socket$NETLINK_NETFILTER",
                "sendmsg$NFT_BATCH_CREATE",
                "recvmsg$NETLINK_DUMP",
                "sendmsg$NFT_BATCH_DELETE",
            ],
            phase_reached="trigger",
            phase_progress=1.0,
            prefix_valid=True,
            resource_chain_intact=True,
            trigger_phase_reached=True,
        )
        self.assertTrue(evidence["target_family_hit"])
        self.assertTrue(evidence["prefix_preserved"])
        self.assertIn("trigger", evidence["phases_exercised"])

    def test_crash_evidence_distinguishes_real_crash(self) -> None:
        evidence = build_crash_evidence(
            crash={
                "kind": "kasan",
                "is_real_crash_signal": True,
                "title": "BUG: KASAN: use-after-free in nf_tables_dump_set",
                "signature": "deadbeef",
                "top_frames": ["nf_tables_dump_set", "nf_tables_getset"],
                "source_files": ["net/netfilter/nf_tables_api.c"],
                "bug_type": "use-after-free",
            },
            exec_result={"timed_out": False},
        )
        self.assertTrue(evidence["crash_detected"])
        self.assertTrue(evidence["real_crash_signal"])
        self.assertEqual(evidence["crash_kind"], "kasan")

    def test_candidate_evidence_requires_specific_pair(self) -> None:
        evidence = build_candidate_evidence(
            candidate_match={
                "uaf_type_match": True,
                "free_use_hint_match": True,
                "match_score": 0.9,
                "crash_frames": ["nf_tables_destroy_set", "nf_tables_dump_set"],
                "crash_files": ["net/netfilter/nf_tables_api.c"],
                "net_enrichment": {
                    "is_net_crash": True,
                    "subsystem_relevance_score": 0.9,
                    "has_teardown_use_pair": True,
                },
            },
            target_profile=self.target_profile,
        )
        self.assertTrue(evidence["path_relevant"])
        self.assertTrue(evidence["specific_candidate_alignment"])
        self.assertEqual(evidence["alignment_quality"], "specific")

    def test_reproducibility_labels(self) -> None:
        self.assertEqual(classify_reproducibility(attempts=3, crash_count=2)["classification"], "reproducible crash")
        self.assertEqual(classify_reproducibility(attempts=3, crash_count=1)["classification"], "unstable crash")
        self.assertEqual(classify_reproducibility(attempts=3, crash_count=0)["classification"], "one-off crash")

    def test_final_verdict_requires_real_crash_bar(self) -> None:
        verdict = classify_net_runtime_verdict(
            preflight_ready=True,
            execution_evidence_summary={
                "target_family_hit": True,
                "phase_reached": "trigger",
                "prefix_preserved": True,
                "trigger_phase_reached": True,
            },
            crash_evidence_summary={
                "crash_detected": True,
                "crash_kind": "kasan",
                "real_crash_signal": True,
            },
            candidate_evidence_summary={
                "path_relevant": True,
                "match_score": 0.9,
                "specific_candidate_alignment": True,
            },
            reproducibility_summary={"crash_count": 2, "classification": "reproducible crash"},
            known_bug_review={"status": "unchecked"},
        )
        self.assertEqual(verdict["verdict_class"], "novelty-unchecked bug candidate")

    def test_known_duplicate_overrides_novelty(self) -> None:
        verdict = classify_net_runtime_verdict(
            preflight_ready=True,
            execution_evidence_summary={
                "target_family_hit": True,
                "phase_reached": "trigger",
                "prefix_preserved": True,
                "trigger_phase_reached": True,
            },
            crash_evidence_summary={
                "crash_detected": True,
                "crash_kind": "kasan",
                "real_crash_signal": True,
            },
            candidate_evidence_summary={
                "path_relevant": True,
                "match_score": 0.9,
                "specific_candidate_alignment": True,
            },
            reproducibility_summary={"crash_count": 2, "classification": "reproducible crash"},
            known_bug_review={"status": "known_duplicate"},
        )
        self.assertEqual(verdict["verdict_class"], "known/likely-duplicate crash candidate")

    def test_lab_classifier_maps_runtime_verdicts(self) -> None:
        result = classify_net_lab_state(
            runtime_verdict={
                "verdict_class": "candidate-correlated live crash",
                "real_crash_bar": {
                    "real_crash_signal": False,
                    "reproduced_at_least_twice": False,
                    "nf_tables_relevant": True,
                    "prefix_and_lifecycle_preserved": True,
                    "specific_candidate_alignment": False,
                },
            },
            exact_source_frames=False,
            lab_only=True,
        )
        self.assertEqual(result["lab_state"], "candidate-correlated crash")


if __name__ == "__main__":
    unittest.main()
