"""Tests for runnable witness emission."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from extractor.import_uafx_bridge_export import import_uafx_bridge_export
from runtime.emit_witness_syz import render_witness
from runtime.validate_witness import validate_witness
from smt.solve_candidate import solve_candidate


ROOT = Path(__file__).resolve().parents[1]
EXPORT_PATH = ROOT / "extractor" / "sample_uafx_kvm_bridge_export.json"
SYZ_ROOT = Path(__file__).resolve().parent / "fixtures" / "syzkaller"


def _sample_candidate_and_plan() -> tuple[dict[str, object], dict[str, object]]:
    export_payload = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    candidate = import_uafx_bridge_export(export_payload, raw_file=str(EXPORT_PATH))
    plan = solve_candidate(candidate)
    return candidate, plan


def test_emit_witness_syz_renders_runnable_kvm_program() -> None:
    candidate, plan = _sample_candidate_and_plan()
    witness = render_witness(candidate, plan, syz_root=SYZ_ROOT)
    summary = validate_witness(candidate, plan, witness, syz_root=SYZ_ROOT)

    assert candidate["candidate_id"] in witness
    assert "# plan_step step_index=0 event=free thread=0 timestamp=0" in witness
    assert "openat$kvm(" in witness
    assert "ioctl$KVM_ARM_VCPU_INIT" in witness
    assert "ioctl$KVM_GET_ONE_REG" in witness
    assert "not a fully runnable syzkaller program" not in witness
    assert summary["valid"] is True
    assert summary["call_count"] == 7


def test_emit_witness_syz_fails_for_unsupported_kvm_template_family() -> None:
    candidate, plan = _sample_candidate_and_plan()
    selected_template_id = plan["execution_hints"]["entry_selection"]["template_id"]

    for entry in candidate["entries"]:
        for template in entry.get("syscall_templates", []):
            if template.get("template_id") == selected_template_id:
                template["calls"] = [
                    "openat$KVM(AT_FDCWD, '/dev/kvm', O_RDWR)",
                    "ioctl$KVM_CREATE_VM(fd_kvm, KVM_CREATE_VM, 0)",
                    "ioctl$KVM_CREATE_DEVICE(fd_vm, KVM_CREATE_DEVICE, &dev)",
                ]

    with pytest.raises(ValueError, match="unsupported witness template: .*future runnable-witness support"):
        render_witness(candidate, plan, syz_root=SYZ_ROOT)
