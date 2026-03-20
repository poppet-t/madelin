from __future__ import annotations

from typing import Any


def _dedupe(seq: list[str]) -> list[str]:
    return list(dict.fromkeys(seq))


def build_mutation_bias(seed: dict[str, Any]) -> dict[str, Any]:
    hints = seed.get("mutation_hints", {})
    focus = [str(v) for v in hints.get("focus_syscall_families", []) if isinstance(v, str)]
    ordering = seed.get("ordering", [])
    keep_edges = []
    for edge in ordering:
        if isinstance(edge, dict) and isinstance(edge.get("before"), str) and isinstance(edge.get("after"), str):
            keep_edges.append(f"{edge['before']}->{edge['after']}")
    return {
        "bias_version": "bridge_bias/v1",
        "candidate_id": seed["candidate_id"],
        "target": f"{seed['target']}/{seed['arch']}",
        "subsystem": seed["subsystem"],
        "preserve_prefix_len": int(hints.get("preserve_prefix_len", len(seed.get("setup_sequence", [])))),
        "focus_syscall_families": _dedupe(focus),
        "prefer_two_thread_schedule": bool(hints.get("prefer_two_thread_schedule", seed.get("threads", 1) >= 2)),
        "prefer_collide": bool(hints.get("prefer_collide", seed.get("flow") == "Con")),
        "mutate_near_steps": _dedupe([str(v) for v in hints.get("mutate_near_steps", []) if isinstance(v, str)]),
        "keep_ordering_edges": _dedupe(keep_edges),
        "stable_prefix_resources": _dedupe([str(v) for v in hints.get("stable_prefix_resources", []) if isinstance(v, str)]),
        "thread_sensitive": {
            "same_process_required": True,
            "prefer_same_thread_for_vcpu_fd": True,
            "notes": [
                "VM ioctls should stay in the process/address space that created the VM.",
                "VCPU ioctls should generally stay on the thread that created the VCPU unless async semantics are known.",
            ],
        },
    }


def build_relation_lines(seed: dict[str, Any]) -> list[str]:
    bias = build_mutation_bias(seed)
    families = bias["focus_syscall_families"]
    edges = [
        ("openat$KVM", "ioctl$KVM_CREATE_VM"),
        ("ioctl$KVM_CREATE_VM", "ioctl$KVM_CREATE_VCPU"),
        ("ioctl$KVM_CREATE_VCPU", "ioctl$KVM_ARM_VCPU_INIT"),
        ("ioctl$KVM_ARM_VCPU_INIT", "ioctl$KVM_RUN"),
        ("ioctl$KVM_CREATE_VM", "ioctl$KVM_CREATE_DEVICE"),
        ("ioctl$KVM_CREATE_DEVICE", "ioctl$KVM_SET_DEVICE_ATTR"),
        ("ioctl$KVM_CREATE_VCPU", "ioctl$KVM_SET_ONE_REG"),
        ("ioctl$KVM_SET_ONE_REG", "ioctl$KVM_GET_ONE_REG"),
        ("ioctl$KVM_GET_ONE_REG", "ioctl$KVM_RUN"),
    ]
    out = []
    for a, b in edges:
        family_a = a.split("$")[-1]
        family_b = b.split("$")[-1]
        if family_a in families or family_b in families or a == "openat$KVM":
            out.append(f"{a},{b}")
    return list(dict.fromkeys(out))
