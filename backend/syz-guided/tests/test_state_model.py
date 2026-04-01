#!/usr/bin/env python3
"""Tests for the state model builder."""

import json
import pathlib
import sys
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from state_model.build_state_model import (
    build_state_model,
    build_target_profile,
    build_relation_graph,
)
from schemas import validate

_FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> dict:
    with open(_FIXTURES / name) as f:
        return json.load(f)


class TestBuildStateModel(unittest.TestCase):
    def setUp(self):
        self.candidate = _load("candidate.json")
        self.plan = _load("witness_plan.json")
        self.sm = build_state_model(
            self.candidate, self.plan,
            "fixtures/candidate.json", "fixtures/witness_plan.json",
        )

    def test_schema_valid(self):
        errors = validate(self.sm, "state_model_v1")
        self.assertEqual(errors, [], f"Schema errors: {errors}")

    def test_candidate_id_preserved(self):
        self.assertEqual(self.sm["candidate_id"], self.candidate["candidate_id"])

    def test_schema_version(self):
        self.assertEqual(self.sm["schema_version"], "state_model/v1")

    def test_subsystem(self):
        self.assertEqual(self.sm["subsystem"], "kvm")

    def test_arch(self):
        self.assertEqual(self.sm["arch"], "arm64")

    def test_bootstrap_phase_has_three_calls(self):
        self.assertEqual(len(self.sm["phases"]["bootstrap"]["calls"]), 3)

    def test_immutable_prefix_matches_bootstrap(self):
        self.assertEqual(
            self.sm["immutable_prefix_len"],
            len(self.sm["phases"]["bootstrap"]["calls"]),
        )

    def test_resource_chain_has_three_resources(self):
        self.assertEqual(len(self.sm["resource_chain"]), 3)
        resources = [r["resource"] for r in self.sm["resource_chain"]]
        self.assertEqual(resources, ["fd_kvm", "fd_vm", "fd_vcpu"])

    def test_precedence_edges_from_barriers(self):
        self.assertEqual(
            len(self.sm["precedence_edges"]),
            len(self.plan["barriers"]),
        )

    def test_score_weights_sum_to_one(self):
        total = sum(self.sm["score_weights"].values())
        self.assertAlmostEqual(total, 1.0, places=5)

    def test_loc0_loc1_populated(self):
        self.assertIsNotNone(self.sm["loc0"]["function"])
        self.assertIsNotNone(self.sm["loc1"]["function"])

    def test_deterministic(self):
        """Same inputs produce identical output."""
        sm2 = build_state_model(
            self.candidate, self.plan,
            "fixtures/candidate.json", "fixtures/witness_plan.json",
        )
        self.assertEqual(json.dumps(self.sm, sort_keys=True), json.dumps(sm2, sort_keys=True))


class TestBuildTargetProfile(unittest.TestCase):
    def setUp(self):
        self.candidate = _load("candidate.json")
        self.tp = build_target_profile(self.candidate)

    def test_schema_valid(self):
        errors = validate(self.tp, "target_profile")
        self.assertEqual(errors, [], f"Schema errors: {errors}")

    def test_focus_frames_include_loc_functions(self):
        self.assertIn("kvm_timer_vcpu_terminate", self.tp["focus_frames"])
        self.assertIn("kvm_timer_should_fire", self.tp["focus_frames"])

    def test_focus_files_include_loc_files(self):
        self.assertIn("arch/arm64/kvm/arch_timer.c", self.tp["focus_files"])

    def test_free_use_hints_have_both_roles(self):
        roles = {h["role"] for h in self.tp["free_use_hints"]}
        self.assertEqual(roles, {"free", "use"})

    def test_preferred_syscalls_not_empty(self):
        self.assertGreater(len(self.tp["preferred_syscalls"]), 0)

    def test_signal_rules_not_empty(self):
        self.assertGreater(len(self.tp["candidate_signal_rules"]), 0)


class TestBuildRelationGraph(unittest.TestCase):
    def setUp(self):
        self.candidate = _load("candidate.json")
        self.plan = _load("witness_plan.json")
        sm = build_state_model(
            self.candidate, self.plan,
            "fixtures/candidate.json", "fixtures/witness_plan.json",
        )
        self.rg = build_relation_graph(self.candidate, self.plan, sm)

    def test_schema_valid(self):
        errors = validate(self.rg, "relation_graph_v1")
        self.assertEqual(errors, [], f"Schema errors: {errors}")

    def test_has_resource_nodes(self):
        resource_nodes = [n for n in self.rg["nodes"] if n["type"] == "resource"]
        self.assertEqual(len(resource_nodes), 3)

    def test_has_syscall_nodes(self):
        syscall_nodes = [n for n in self.rg["nodes"] if n["type"] == "syscall"]
        self.assertGreater(len(syscall_nodes), 0)

    def test_has_resource_flow_edges(self):
        rf_edges = [e for e in self.rg["edges"] if e["type"] == "resource_flow"]
        self.assertGreater(len(rf_edges), 0)

    def test_has_must_precede_edges(self):
        mp_edges = [e for e in self.rg["edges"] if e["type"] == "must_precede"]
        self.assertGreater(len(mp_edges), 0)

    def test_mutation_constraints_not_empty(self):
        self.assertGreater(len(self.rg["mutation_constraints"]), 0)


if __name__ == "__main__":
    unittest.main()
