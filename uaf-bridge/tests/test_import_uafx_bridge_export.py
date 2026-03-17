from __future__ import annotations

import json
from pathlib import Path

from extractor.import_uafx_bridge_export import import_uafx_bridge_export


EXPORT_PATH = Path(__file__).resolve().parents[1] / "extractor" / "sample_uafx_kvm_bridge_export.json"


def test_import_uafx_bridge_export_emits_kvm_candidate() -> None:
    export_payload = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    candidate = import_uafx_bridge_export(export_payload, raw_file=str(EXPORT_PATH))

    assert candidate["analysis_context"]["kernel_area"] == "arch/arm64/kvm"
    assert candidate["analysis_context"]["subsystem"] == "kvm"
    assert candidate["flow"] == "Con"
    assert candidate["source"]["tool"] == "uafx-bridge-import"
    assert candidate["raw_warning"]["warning_id"] == "uafx-kvm-arm64-0001"
    assert candidate["status"]["mapping_confidence"] == "manual"
    assert candidate["status"]["supported"] is True

    entry_funcs = [entry["entry_func"] for entry in candidate["entries"]]
    assert "kvm_vcpu_ioctl" in entry_funcs
    assert "kvm_vm_ioctl_create_vcpu" in entry_funcs

    kvm_entry = next(entry for entry in candidate["entries"] if entry["entry_func"] == "kvm_vcpu_ioctl")
    assert any("/dev/kvm" in call for call in kvm_entry["syscall_templates"][0]["calls"])
    assert any(reason.startswith("heuristic predicate preserved") for reason in candidate["status"]["unsupported_reasons"])
