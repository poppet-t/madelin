from __future__ import annotations

from pathlib import Path

from mapping.syz_descriptions import harvest_kvm_descriptions


SYZ_ROOT = Path(__file__).resolve().parent / "fixtures" / "syzkaller"


def test_harvest_kvm_descriptions_reads_supported_subset() -> None:
    descriptions = harvest_kvm_descriptions(SYZ_ROOT)

    assert descriptions["syzkaller_root"] == str(SYZ_ROOT.resolve())
    assert descriptions["constants"]["KVM_CREATE_VM"] == 44545
    assert descriptions["constants"]["KVM_ARM_TARGET_GENERIC_V8"] == 5
    assert descriptions["syscalls"]["openat$KVM"]["syz_name"] == "openat$kvm"
    assert descriptions["syscalls"]["KVM_CREATE_VCPU"]["bridge_input_resource"] == "fd_vm"
    assert descriptions["syscalls"]["KVM_ARM_VCPU_INIT"]["struct_arg"] == "kvm_vcpu_init"
    assert descriptions["structs"]["kvm_vcpu_init"]["size"] == 32
    assert descriptions["structs"]["kvm_one_reg"]["size"] == 16
