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


def test_validate_witness_accepts_emitted_program() -> None:
    candidate, plan = _sample_candidate_and_plan()
    witness = render_witness(candidate, plan, syz_root=SYZ_ROOT)

    summary = validate_witness(candidate, plan, witness, syz_root=SYZ_ROOT)

    assert summary["valid"] is True
    assert summary["representative_template_id"] == "kvm_vcpu_ioctl:file_ioctl:kvm-arm64:regs:v1"


def test_validate_witness_rejects_broken_resource_flow() -> None:
    candidate, plan = _sample_candidate_and_plan()
    witness = render_witness(candidate, plan, syz_root=SYZ_ROOT)
    broken = witness.replace(
        "r1 = ioctl$KVM_CREATE_VM(r0, 0xae01, 0x0)",
        "r1 = ioctl$KVM_CREATE_VM(r9, 0xae01, 0x0)",
        1,
    )

    with pytest.raises(ValueError, match="current fd_kvm witness variable"):
        validate_witness(candidate, plan, broken, syz_root=SYZ_ROOT)


def test_validate_witness_rejects_wrong_plan_metadata() -> None:
    candidate, plan = _sample_candidate_and_plan()
    witness = render_witness(candidate, plan, syz_root=SYZ_ROOT)
    plan_line = next(line for line in witness.splitlines() if line.startswith("# plan_step "))
    broken_line = plan_line.replace("thread=0", "thread=1", 1) if "thread=0" in plan_line else plan_line.replace("thread=1", "thread=0", 1)
    broken = witness.replace(plan_line, broken_line, 1)

    with pytest.raises(ValueError, match="plan_step metadata"):
        validate_witness(candidate, plan, broken, syz_root=SYZ_ROOT)
