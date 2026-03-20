#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

SETUP_PREFIXES: list[tuple[str, list[str]]] = [
    ("prefix_1", ["openat$KVM"]),
    ("prefix_2", ["openat$KVM", "ioctl$KVM_CREATE_VM"]),
    ("prefix_3", ["openat$KVM", "ioctl$KVM_CREATE_VM", "ioctl$KVM_CREATE_VCPU"]),
]

TRIGGER_FAMILIES = [
    "KVM_RUN",
    "KVM_ARM_VCPU_INIT",
    "KVM_SET_ONE_REG",
    "KVM_GET_ONE_REG",
    "KVM_CREATE_DEVICE",
    "KVM_SET_DEVICE_ATTR",
]

KVM_FAMILIES = [
    "openat$KVM",
    "KVM_CREATE_VM",
    "KVM_CREATE_VCPU",
    *TRIGGER_FAMILIES,
]

TOP_SYSCALL_LIMIT = 20


def resolve_corpus_dir(path: Path) -> Path:
    if (path / "corpus").is_dir():
        return path / "corpus"
    if path.is_dir():
        has_subdirs = any(child.is_dir() for child in path.iterdir())
        if not has_subdirs:
            return path
    raise ValueError(f"bad corpus/output dir: {path}")


def iter_prog_files(path: Path) -> Iterable[Path]:
    corpus_dir = resolve_corpus_dir(path)
    for child in sorted(corpus_dir.iterdir()):
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


def family_match(name: str, family: str) -> bool:
    if family == "openat$KVM":
        return name == family
    return family in name


def percent(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return 100.0 * numerator / denominator


def summarize_corpus(path: Path) -> dict:
    corpus_dir = resolve_corpus_dir(path)
    counter: Counter[str] = Counter()
    programs: list[list[str]] = []

    for prog_file in iter_prog_files(path):
        syscalls = extract_syscalls(prog_file.read_text(encoding="utf-8", errors="ignore"))
        programs.append(syscalls)
        counter.update(syscalls)

    program_count = len(programs)
    total_syscalls = sum(counter.values())
    kvm_related_total = sum(count for name, count in counter.items() if "KVM" in name)

    prefix_survival: dict[str, dict] = {}
    for key, sequence in SETUP_PREFIXES:
        count = sum(1 for syscalls in programs if syscalls[: len(sequence)] == sequence)
        prefix_survival[key] = {
            "sequence": sequence,
            "count": count,
            "percent": percent(count, program_count),
        }

    trigger_program_counts: dict[str, int] = {}
    programs_with_any_trigger = 0
    for family in TRIGGER_FAMILIES:
        trigger_program_counts[family] = sum(
            1 for syscalls in programs if any(family_match(name, family) for name in syscalls)
        )
    for syscalls in programs:
        if any(any(family_match(name, family) for name in syscalls) for family in TRIGGER_FAMILIES):
            programs_with_any_trigger += 1

    kvm_family_counts = {
        family: sum(count for name, count in counter.items() if family_match(name, family))
        for family in KVM_FAMILIES
    }
    top_syscalls = sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:TOP_SYSCALL_LIMIT]

    return {
        "path": str(path),
        "corpus_dir": str(corpus_dir),
        "program_count": program_count,
        "total_syscall_count": total_syscalls,
        "avg_syscalls_per_program": (total_syscalls / program_count) if program_count else 0.0,
        "kvm_related_total": kvm_related_total,
        "kvm_related_percent": percent(kvm_related_total, total_syscalls),
        "prefix_survival": prefix_survival,
        "trigger_presence": {
            "families": TRIGGER_FAMILIES,
            "programs_with_any_trigger": programs_with_any_trigger,
            "programs_with_any_trigger_percent": percent(programs_with_any_trigger, program_count),
            "per_family_program_counts": trigger_program_counts,
        },
        "kvm_family_counts": kvm_family_counts,
        "top_syscalls": top_syscalls,
        "syscall_histogram": dict(sorted(counter.items())),
    }


def compare_summaries(left: dict, right: dict) -> dict:
    prefix_survival_deltas = {}
    for key, _sequence in SETUP_PREFIXES:
        prefix_survival_deltas[key] = {
            "sequence": right["prefix_survival"][key]["sequence"],
            "count_delta": right["prefix_survival"][key]["count"] - left["prefix_survival"][key]["count"],
            "percent_delta": right["prefix_survival"][key]["percent"] - left["prefix_survival"][key]["percent"],
        }

    trigger_program_deltas = {
        family: right["trigger_presence"]["per_family_program_counts"][family]
        - left["trigger_presence"]["per_family_program_counts"][family]
        for family in TRIGGER_FAMILIES
    }
    kvm_family_deltas = {
        family: right["kvm_family_counts"][family] - left["kvm_family_counts"][family]
        for family in KVM_FAMILIES
    }

    return {
        "left": left["path"],
        "right": right["path"],
        "program_count_delta": right["program_count"] - left["program_count"],
        "total_syscall_count_delta": right["total_syscall_count"] - left["total_syscall_count"],
        "avg_syscalls_per_program_delta": right["avg_syscalls_per_program"] - left["avg_syscalls_per_program"],
        "kvm_related_total_delta": right["kvm_related_total"] - left["kvm_related_total"],
        "kvm_related_percent_delta": right["kvm_related_percent"] - left["kvm_related_percent"],
        "prefix_survival_deltas": prefix_survival_deltas,
        "programs_with_any_trigger_delta": (
            right["trigger_presence"]["programs_with_any_trigger"]
            - left["trigger_presence"]["programs_with_any_trigger"]
        ),
        "programs_with_any_trigger_percent_delta": (
            right["trigger_presence"]["programs_with_any_trigger_percent"]
            - left["trigger_presence"]["programs_with_any_trigger_percent"]
        ),
        "trigger_program_deltas": trigger_program_deltas,
        "kvm_family_deltas": kvm_family_deltas,
    }


def render_summary(summary: dict) -> str:
    lines = [
        f"path: {summary['path']}",
        f"corpus_dir: {summary['corpus_dir']}",
        f"program_count: {summary['program_count']}",
        f"total_syscall_count: {summary['total_syscall_count']}",
        f"avg_syscalls_per_program: {summary['avg_syscalls_per_program']:.2f}",
        f"kvm_related_total: {summary['kvm_related_total']}",
        f"kvm_related_percent: {summary['kvm_related_percent']:.2f}",
        "prefix_survival:",
    ]
    for key, _sequence in SETUP_PREFIXES:
        item = summary["prefix_survival"][key]
        lines.append(
            f"  - {key}: {item['count']} ({item['percent']:.2f}%) [{', '.join(item['sequence'])}]"
        )
    lines.extend(
        [
            "trigger_presence:",
            "  - any_trigger: "
            f"{summary['trigger_presence']['programs_with_any_trigger']} "
            f"({summary['trigger_presence']['programs_with_any_trigger_percent']:.2f}%)",
        ]
    )
    for family in TRIGGER_FAMILIES:
        lines.append(
            f"  - {family}: {summary['trigger_presence']['per_family_program_counts'][family]}"
        )
    lines.append("kvm_family_counts:")
    for family in KVM_FAMILIES:
        lines.append(f"  - {family}: {summary['kvm_family_counts'][family]}")
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
        f"avg_syscalls_per_program_delta: {compare['avg_syscalls_per_program_delta']:.2f}",
        f"kvm_related_total_delta: {compare['kvm_related_total_delta']}",
        f"kvm_related_percent_delta: {compare['kvm_related_percent_delta']:.2f}",
        "prefix_survival_deltas:",
    ]
    for key, _sequence in SETUP_PREFIXES:
        item = compare["prefix_survival_deltas"][key]
        lines.append(
            f"  - {key}: count_delta={item['count_delta']}, percent_delta={item['percent_delta']:.2f}"
        )
    lines.extend(
        [
            f"programs_with_any_trigger_delta: {compare['programs_with_any_trigger_delta']}",
            "programs_with_any_trigger_percent_delta: "
            f"{compare['programs_with_any_trigger_percent_delta']:.2f}",
            "trigger_program_deltas:",
        ]
    )
    for family in TRIGGER_FAMILIES:
        lines.append(f"  - {family}: {compare['trigger_program_deltas'][family]}")
    lines.append("kvm_family_deltas:")
    for family in KVM_FAMILIES:
        lines.append(f"  - {family}: {compare['kvm_family_deltas'][family]}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure KVM setup-prefix survival and trigger-family presence in one corpus, or compare unseeded vs seeded corpora"
    )
    parser.add_argument("left", help="Corpus dir or output dir containing corpus/")
    parser.add_argument("right", nargs="?", help="Optional seeded corpus/output dir for comparison")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human-readable text")
    args = parser.parse_args()

    try:
        left = summarize_corpus(Path(args.left))
        if args.right:
            right = summarize_corpus(Path(args.right))
            compare = compare_summaries(left, right)
            if args.json:
                print(json.dumps({"left": left, "right": right, "compare": compare}, indent=2))
            else:
                print(render_summary(left), end="")
                print(render_summary(right), end="")
                print(render_compare(compare), end="")
        else:
            if args.json:
                print(json.dumps(left, indent=2))
            else:
                print(render_summary(left), end="")
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
