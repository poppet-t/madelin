from __future__ import annotations

import json
from pathlib import Path

from extractor.import_uafx_bridge_export import import_uafx_bridge_export
from runtime.export_mock_seed import export_mock_seed
from smt.solve_candidate import solve_candidate


EXPORT_PATH = Path(__file__).resolve().parents[1] / "extractor" / "sample_uafx_kvm_bridge_export.json"


def test_export_mock_seed_emits_kvm_concurrency_seed() -> None:
    export_payload = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    candidate = import_uafx_bridge_export(export_payload, raw_file=str(EXPORT_PATH))
    plan = solve_candidate(candidate)
    seed = export_mock_seed(candidate, plan)

    assert seed["seed_version"] == "mock_seed/v1"
    assert seed["target"] == "linux"
    assert seed["arch"] == "arm64"
    assert seed["subsystem"] == "kvm"
    assert seed["flow"] == "Con"
    assert seed["threads"] == 2
    assert seed["mutation_hints"]["prefer_two_thread_schedule"] is True
    assert seed["mutation_hints"]["prefer_collide"] is True
    assert seed["mutation_hints"]["preserve_prefix_len"] >= 3
    assert any(step["text"].startswith("openat$KVM") for step in seed["setup_sequence"])
    assert any("KVM_CREATE_VM" in step["text"] for step in seed["setup_sequence"])
    assert any("KVM_CREATE_VCPU" in step["text"] for step in seed["setup_sequence"])
    assert any("KVM_RUN" in step["text"] for step in seed["trigger_sequence"])
    assert "KVM_ARM_VCPU_INIT" in seed["focus_syscall_families"]
    assert any(predicate["name"] == "kvm_vcpu_fd_ready" for predicate in seed["predicates"])
    assert any(edge["before"] == "free" and edge["after"] == "use" for edge in seed["ordering"])
    assert seed["debug"]["selected_entry_func"] in {"kvm_vcpu_ioctl", "kvm_vm_ioctl_create_vcpu"}
