"""Syscall template generation for entry classes."""

from __future__ import annotations

from typing import Any


KVM_ARM64_BASE_SETUP: list[str] = [
    "openat$KVM(AT_FDCWD, '/dev/kvm', O_RDWR)",
    "ioctl$KVM_CREATE_VM(fd_kvm, KVM_CREATE_VM, 0)",
    "ioctl$KVM_CREATE_VCPU(fd_vm, KVM_CREATE_VCPU, 0)",
]

IO_URING_BASE_SETUP: list[str] = [
    "io_uring_setup(8, &params)",
    "io_uring_register$IORING_REGISTER_FILES(fd_ring, &files, 1)",
]

NETLINK_BASE_SETUP: list[str] = [
    "socket$NETLINK_NETFILTER(AF_NETLINK, SOCK_RAW, NETLINK_NETFILTER)",
    "sendmsg$NFT_BATCH_CREATE(fd_nl, &msg_create, 0)",
    "sendmsg$NFT_BATCH_UPDATE(fd_nl, &msg_update, 0)",
]

BPF_BASE_SETUP: list[str] = [
    "bpf$MAP_CREATE(&map_create)",
    "bpf$PROG_LOAD(&prog_load)",
    "bpf$BPF_LINK_CREATE(&link_create)",
]

FS_MOUNT_BASE_SETUP: list[str] = [
    "fsopen('tmpfs', 0)",
    "fsconfig$SET_STRING(fd_fsctx, FSCONFIG_SET_STRING, 'size', '4096', 0)",
    "fsmount(fd_fsctx, 0, 0)",
]

FUSE_BASE_SETUP: list[str] = [
    "openat$FUSE_DEV(AT_FDCWD, '/dev/fuse', O_RDWR)",
    "mount$FUSE('/dev/fuse', '/tmp/madelin', 'fuse', 0, 'fd=%d')",
    "read$FUSE_DEV(fd_fuse, data, 0x100)",
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


def _io_uring_templates(entry_func: str, entry_kind: str) -> list[dict[str, Any]]:
    calls = [*IO_URING_BASE_SETUP]
    if entry_kind in {"fd_dup_or_share", "poll_wait"} or "dup" in entry_func.lower():
        calls.append("dup$io_uring(fd_ring)")
    if entry_kind == "poll_wait" or "poll" in entry_func.lower():
        calls.append("poll$io_uring(fd_ring, &pollfds, 1, 0)")
    calls.extend([
        "io_uring_enter(fd_ring, 1, 1, 0, NULL, 0)",
        "close$io_uring(fd_ring)",
    ])
    return [
        _template(
            f"{entry_func}:{entry_kind}:io-uring-arm64:v1",
            calls,
            ["fd_ring"],
            "Hardware-light io_uring scaffold covering setup/register/enter/teardown.",
        )
    ]


def _net_templates(entry_func: str, entry_kind: str) -> list[dict[str, Any]]:
    calls = [
        *NETLINK_BASE_SETUP,
        "recvmsg$NETLINK_DUMP(fd_nl, &msg_dump, 0)",
        "sendmsg$NFT_BATCH_DELETE(fd_nl, &msg_delete, 0)",
        "close$NETLINK_NETFILTER(fd_nl)",
    ]
    return [
        _template(
            f"{entry_func}:{entry_kind}:net-netfilter-arm64:v1",
            calls,
            ["fd_nl"],
            "Hardware-light netlink/netfilter scaffold covering create/update/dump/delete flows.",
        )
    ]


def _bpf_templates(entry_func: str, entry_kind: str) -> list[dict[str, Any]]:
    calls = [
        *BPF_BASE_SETUP,
        "bpf$MAP_UPDATE_ELEM(fd_map, &key, &value, 0)",
        "bpf$LINK_DETACH(fd_link)",
        "close$bpf_link(fd_link)",
        "close$bpf_prog(fd_prog)",
        "close$bpf_map(fd_map)",
    ]
    return [
        _template(
            f"{entry_func}:{entry_kind}:bpf-arm64:v1",
            calls,
            ["fd_map", "fd_prog", "fd_link"],
            "Hardware-light eBPF scaffold covering map/program/link create/attach/detach lifetimes.",
        )
    ]


def _fs_templates(entry_func: str, entry_kind: str) -> list[dict[str, Any]]:
    if entry_kind == "fuse_control" or "fuse" in entry_func.lower():
        calls = [
            *FUSE_BASE_SETUP,
            "ioctl$FUSE_DEV_IOC_CLONE(fd_fuse, &clone)",
            "close$FUSE_DEV(fd_fuse)",
        ]
        return [
            _template(
                f"{entry_func}:{entry_kind}:fs-fuse-arm64:v1",
                calls,
                ["fd_fuse"],
                "Hardware-light FUSE scaffold covering control-plane setup and teardown.",
            )
        ]

    calls = [
        *FS_MOUNT_BASE_SETUP,
        "move_mount(fd_mount, '', AT_FDCWD, '/tmp/madelin', 0)",
        "umount2('/tmp/madelin', 0)",
        "close$fsmount(fd_mount)",
        "close$fsopen(fd_fsctx)",
    ]
    return [
        _template(
            f"{entry_func}:{entry_kind}:fs-mount-arm64:v1",
            calls,
            ["fd_fsctx", "fd_mount"],
            "Hardware-light mount API scaffold covering fsopen/fsconfig/fsmount/move_mount teardown.",
        )
    ]


def generate_templates(entry_func: str, entry_kind: str, analysis_context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Generate syscall templates for a classified entry."""
    subsystem = None
    if isinstance(analysis_context, dict):
        subsystem = analysis_context.get("subsystem")

    if subsystem == "kvm" or entry_func.startswith("kvm_"):
        kvm_templates = _kvm_ioctl_templates(entry_func)
        if kvm_templates:
            return kvm_templates

    if subsystem == "io_uring" or entry_kind in {"io_uring_setup", "io_uring_register", "io_uring_enter", "fd_dup_or_share", "poll_wait", "mmap_interaction", "close_teardown"}:
        return _io_uring_templates(entry_func, entry_kind)

    if subsystem == "net" or entry_kind in {"netlink_send", "netlink_recv", "close_teardown", "poll_wait"}:
        return _net_templates(entry_func, entry_kind)

    if subsystem == "bpf" or entry_kind == "bpf_cmd":
        return _bpf_templates(entry_func, entry_kind)

    if subsystem == "fs" or entry_kind in {"mount_api_step", "fuse_control"}:
        return _fs_templates(entry_func, entry_kind)

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
