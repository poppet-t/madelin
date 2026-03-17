"""Syscall template generation for entry classes."""

from __future__ import annotations

from typing import Any


KVM_ARM64_BASE_SETUP: list[str] = [
    "openat$KVM(AT_FDCWD, '/dev/kvm', O_RDWR)",
    "ioctl$KVM_CREATE_VM(fd_kvm, KVM_CREATE_VM, 0)",
    "ioctl$KVM_CREATE_VCPU(fd_vm, KVM_CREATE_VCPU, 0)",
]


def _template(template_id: str, calls: list[str], required_resources: list[str], notes: str) -> dict[str, Any]:
    return {
        "template_id": template_id,
        "calls": calls,
        "required_resources": required_resources,
        "notes": notes,
    }


def _kvm_ioctl_templates(entry_func: str) -> list[dict[str, Any]]:
    if entry_func == "kvm_vm_ioctl_create_vcpu":
        return [
            _template(
                "kvm_vm_ioctl_create_vcpu:file_ioctl:kvm-arm64:v1",
                [*KVM_ARM64_BASE_SETUP],
                ["fd_kvm", "fd_vm", "fd_vcpu"],
                "Grounded KVM/arm64 setup scaffold for VM/VCPU creation.",
            )
        ]

    if entry_func == "kvm_vcpu_ioctl":
        return [
            _template(
                "kvm_vcpu_ioctl:file_ioctl:kvm-arm64:v2",
                [
                    *KVM_ARM64_BASE_SETUP,
                    "ioctl$KVM_ARM_VCPU_INIT(fd_vcpu, KVM_ARM_VCPU_INIT, &init)",
                    "ioctl$KVM_RUN(fd_vcpu, KVM_RUN, 0)",
                ],
                ["fd_kvm", "fd_vm", "fd_vcpu"],
                "Grounded KVM/arm64 VCPU execution scaffold with architecture init and run steps.",
            ),
            _template(
                "kvm_vcpu_ioctl:file_ioctl:kvm-arm64:regs:v1",
                [
                    *KVM_ARM64_BASE_SETUP,
                    "ioctl$KVM_ARM_VCPU_INIT(fd_vcpu, KVM_ARM_VCPU_INIT, &init)",
                    "ioctl$KVM_SET_ONE_REG(fd_vcpu, KVM_SET_ONE_REG, &one_reg)",
                    "ioctl$KVM_GET_ONE_REG(fd_vcpu, KVM_GET_ONE_REG, &one_reg)",
                    "ioctl$KVM_RUN(fd_vcpu, KVM_RUN, 0)",
                ],
                ["fd_kvm", "fd_vm", "fd_vcpu"],
                "Grounded KVM/arm64 register-access scaffold for ioctl-heavy VCPU paths.",
            ),
        ]

    if entry_func == "kvm_vm_ioctl":
        return [
            _template(
                "kvm_vm_ioctl:file_ioctl:kvm-arm64:v1",
                [
                    "openat$KVM(AT_FDCWD, '/dev/kvm', O_RDWR)",
                    "ioctl$KVM_CREATE_VM(fd_kvm, KVM_CREATE_VM, 0)",
                    "ioctl$KVM_CREATE_DEVICE(fd_vm, KVM_CREATE_DEVICE, &dev)",
                    "ioctl$KVM_SET_DEVICE_ATTR(fd_device, KVM_SET_DEVICE_ATTR, &attr)",
                ],
                ["fd_kvm", "fd_vm", "fd_device"],
                "Heuristic KVM/arm64 VM-level scaffold for device creation and configuration.",
            )
        ]

    lowered = entry_func.lower()
    if "vgic" in lowered or "device_attr" in lowered or "create_device" in lowered:
        return [
            _template(
                f"{entry_func}:file_ioctl:kvm-arm64:device:v1",
                [
                    "openat$KVM(AT_FDCWD, '/dev/kvm', O_RDWR)",
                    "ioctl$KVM_CREATE_VM(fd_kvm, KVM_CREATE_VM, 0)",
                    "ioctl$KVM_CREATE_DEVICE(fd_vm, KVM_CREATE_DEVICE, &dev)",
                    "ioctl$KVM_SET_DEVICE_ATTR(fd_device, KVM_SET_DEVICE_ATTR, &attr)",
                ],
                ["fd_kvm", "fd_vm", "fd_device"],
                "Heuristic KVM/arm64 device-attribute scaffold for VGIC/device handler paths.",
            )
        ]

    if "set_one_reg" in lowered or "get_one_reg" in lowered or ("reg" in lowered and "kvm" in lowered):
        return [
            _template(
                f"{entry_func}:file_ioctl:kvm-arm64:reg:v1",
                [
                    *KVM_ARM64_BASE_SETUP,
                    "ioctl$KVM_ARM_VCPU_INIT(fd_vcpu, KVM_ARM_VCPU_INIT, &init)",
                    "ioctl$KVM_SET_ONE_REG(fd_vcpu, KVM_SET_ONE_REG, &one_reg)",
                    "ioctl$KVM_GET_ONE_REG(fd_vcpu, KVM_GET_ONE_REG, &one_reg)",
                ],
                ["fd_kvm", "fd_vm", "fd_vcpu"],
                "Heuristic KVM/arm64 register-access scaffold.",
            )
        ]

    if "irq" in lowered or "timer" in lowered or "pmu" in lowered:
        return [
            _template(
                f"{entry_func}:file_ioctl:kvm-arm64:irq-timer:v1",
                [
                    *KVM_ARM64_BASE_SETUP,
                    "ioctl$KVM_ARM_VCPU_INIT(fd_vcpu, KVM_ARM_VCPU_INIT, &init)",
                    "ioctl$KVM_IRQ_LINE(fd_vm, KVM_IRQ_LINE, &irq)",
                    "ioctl$KVM_RUN(fd_vcpu, KVM_RUN, 0)",
                ],
                ["fd_kvm", "fd_vm", "fd_vcpu"],
                "Heuristic KVM/arm64 IRQ/timer/PMU scaffold.",
            )
        ]

    return []


def generate_templates(entry_func: str, entry_kind: str) -> list[dict[str, Any]]:
    """Generate placeholder syscall templates for a classified entry."""
    kvm_templates = _kvm_ioctl_templates(entry_func)
    if kvm_templates:
        return kvm_templates

    template_id_base = entry_func.replace(" ", "_")

    if entry_kind == "file_ioctl":
        return [
            {
                "template_id": f"{template_id_base}:file_ioctl:v1",
                "calls": [
                    "openat$DEV(AT_FDCWD, '/dev/uaf_demo', O_RDWR)",
                    "ioctl$CMD(fd_dev, 0x0, 0x0)",
                ],
                "required_resources": ["fd_dev"],
                "notes": "Placeholder file-ioctl template.",
            }
        ]

    if entry_kind == "file_read":
        return [
            {
                "template_id": f"{template_id_base}:file_read:v1",
                "calls": [
                    "openat$DEV(AT_FDCWD, '/dev/uaf_demo', O_RDONLY)",
                    "read(fd_dev, data, 0x100)",
                ],
                "required_resources": ["fd_dev", "data"],
                "notes": "Placeholder file-read template.",
            }
        ]

    if entry_kind == "file_write":
        return [
            {
                "template_id": f"{template_id_base}:file_write:v1",
                "calls": [
                    "openat$DEV(AT_FDCWD, '/dev/uaf_demo', O_WRONLY)",
                    "write(fd_dev, data, 0x100)",
                ],
                "required_resources": ["fd_dev", "data"],
                "notes": "Placeholder file-write template.",
            }
        ]

    if entry_kind == "sysfs_show":
        return [
            {
                "template_id": f"{template_id_base}:sysfs_show:v1",
                "calls": [
                    "openat$SYSFS(AT_FDCWD, '/sys/kernel/uaf_demo', O_RDONLY)",
                    "read(fd_sysfs, data, 0x100)",
                ],
                "required_resources": ["fd_sysfs", "data"],
                "notes": "Placeholder sysfs-show template.",
            }
        ]

    if entry_kind == "sysfs_store":
        return [
            {
                "template_id": f"{template_id_base}:sysfs_store:v1",
                "calls": [
                    "openat$SYSFS(AT_FDCWD, '/sys/kernel/uaf_demo', O_WRONLY)",
                    "write(fd_sysfs, data, 0x100)",
                ],
                "required_resources": ["fd_sysfs", "data"],
                "notes": "Placeholder sysfs-store template.",
            }
        ]

    return []
