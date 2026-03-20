#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Iterable

KVM_FAMILIES = [
    "openat$KVM",
    "KVM_CREATE_VM",
    "KVM_CREATE_VCPU",
    "KVM_RUN",
    "KVM_ARM_VCPU_INIT",
    "KVM_SET_ONE_REG",
    "KVM_GET_ONE_REG",
    "KVM_CREATE_DEVICE",
    "KVM_SET_DEVICE_ATTR",
]


def iter_prog_files(path: Path) -> Iterable[Path]:
    base = path / "corpus" if (path / "corpus").is_dir() else path
    for child in sorted(base.iterdir()):
        if child.is_file():
            yield child


def extract_syscalls(program_text: str) -> list[str]:
    syscalls: list[str] = []
    for raw_line in program_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if " = " in line:
            _, line = line.split(" = ", 1)
        if "(" in line:
            syscalls.append(line.split("(", 1)[0].strip())
    return syscalls


def summarize_corpus(path: Path) -> dict:
    counter: Counter[str] = Counter()
    program_count = 0
    for prog_file in iter_prog_files(path):
        program_count += 1
        counter.update(extract_syscalls(prog_file.read_text(encoding="utf-8", errors="ignore")))
    total_syscalls = sum(counter.values())
    kvm_counts = {family: sum(count for name, count in counter.items() if (name == family or family in name)) for family in KVM_FAMILIES}
    kvm_related_total = sum(count for name, count in counter.items() if "KVM" in name)
    return {
        "path": str(path),
        "program_count": program_count,
        "total_syscall_count": total_syscalls,
        "avg_syscalls_per_program": (total_syscalls / program_count) if program_count else 0.0,
        "kvm_related_total": kvm_related_total,
        "kvm_related_percent": (100.0 * kvm_related_total / total_syscalls) if total_syscalls else 0.0,
        "kvm_family_counts": kvm_counts,
        "top_syscalls": counter.most_common(20),
        "syscall_histogram": dict(counter),
    }


def compare_summaries(left: dict, right: dict) -> dict:
    families = sorted(set(left["kvm_family_counts"]) | set(right["kvm_family_counts"]))
    deltas = {
        family: right["kvm_family_counts"].get(family, 0) - left["kvm_family_counts"].get(family, 0)
        for family in families
    }
    return {
        "left": left["path"],
        "right": right["path"],
        "program_count_delta": right["program_count"] - left["program_count"],
        "total_syscall_count_delta": right["total_syscall_count"] - left["total_syscall_count"],
        "kvm_related_total_delta": right["kvm_related_total"] - left["kvm_related_total"],
        "kvm_related_percent_delta": right["kvm_related_percent"] - left["kvm_related_percent"],
        "kvm_family_deltas": deltas,
    }


def render_summary(summary: dict) -> str:
    lines = [
        f"path: {summary['path']}",
        f"program_count: {summary['program_count']}",
        f"total_syscall_count: {summary['total_syscall_count']}",
        f"avg_syscalls_per_program: {summary['avg_syscalls_per_program']:.2f}",
        f"kvm_related_total: {summary['kvm_related_total']}",
        f"kvm_related_percent: {summary['kvm_related_percent']:.2f}",
        "kvm_family_counts:",
    ]
    for family, count in summary["kvm_family_counts"].items():
        lines.append(f"  - {family}: {count}")
    lines.append("top_syscalls:")
    for name, count in summary["top_syscalls"]:
        lines.append(f"  - {name}: {count}")
    return "\n".join(lines) + "\n"


def render_compare(compare: dict) -> str:
    lines = [
        f"left: {compare['left']}",
        f"right: {compare['right']}",
        f"program_count_delta: {compare['program_count_delta']}",
        f"total_syscall_count_delta: {compare['total_syscall_count_delta']}",
        f"kvm_related_total_delta: {compare['kvm_related_total_delta']}",
        f"kvm_related_percent_delta: {compare['kvm_related_percent_delta']:.2f}",
        "kvm_family_deltas:",
    ]
    for family, delta in compare["kvm_family_deltas"].items():
        lines.append(f"  - {family}: {delta}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize syscall usage in a corpus directory; compare two corpora if given")
    parser.add_argument("left", help="Corpus dir or output dir containing corpus/")
    parser.add_argument("right", nargs="?", help="Optional second corpus dir or output dir for comparison")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human-readable text")
    args = parser.parse_args()

    left = summarize_corpus(Path(args.left))
    if args.right:
        right = summarize_corpus(Path(args.right))
        compare = compare_summaries(left, right)
        if args.json:
            print(json.dumps({"left": left, "right": right, "compare": compare}, indent=2, sort_keys=True))
        else:
            print(render_summary(left), end="")
            print(render_summary(right), end="")
            print(render_compare(compare), end="")
    else:
        if args.json:
            print(json.dumps(left, indent=2, sort_keys=True))
        else:
            print(render_summary(left), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
