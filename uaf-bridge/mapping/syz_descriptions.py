"""Harvest a narrow KVM/arm64 syzkaller description subset for runnable witnesses."""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
import re
from typing import Any


SYZ_ROOT_ENV = "UAF_BRIDGE_SYZ_ROOT"

SUPPORTED_KVM_WITNESS_FAMILIES: dict[str, dict[str, str | None]] = {
    "openat$KVM": {
        "syz_name": "openat$kvm",
        "event": "init_resource",
        "constant_name": None,
        "bridge_input_resource": None,
        "bridge_output_resource": "fd_kvm",
    },
    "KVM_CREATE_VM": {
        "syz_name": "ioctl$KVM_CREATE_VM",
        "event": "init_resource",
        "constant_name": "KVM_CREATE_VM",
        "bridge_input_resource": "fd_kvm",
        "bridge_output_resource": "fd_vm",
    },
    "KVM_CREATE_VCPU": {
        "syz_name": "ioctl$KVM_CREATE_VCPU",
        "event": "init_resource",
        "constant_name": "KVM_CREATE_VCPU",
        "bridge_input_resource": "fd_vm",
        "bridge_output_resource": "fd_vcpu",
    },
    "KVM_ARM_VCPU_INIT": {
        "syz_name": "ioctl$KVM_ARM_VCPU_INIT",
        "event": "escape",
        "constant_name": "KVM_ARM_VCPU_INIT",
        "bridge_input_resource": "fd_vcpu",
        "bridge_output_resource": None,
    },
    "KVM_SET_ONE_REG": {
        "syz_name": "ioctl$KVM_SET_ONE_REG",
        "event": "fetch",
        "constant_name": "KVM_SET_ONE_REG",
        "bridge_input_resource": "fd_vcpu",
        "bridge_output_resource": None,
    },
    "KVM_GET_ONE_REG": {
        "syz_name": "ioctl$KVM_GET_ONE_REG",
        "event": "fetch",
        "constant_name": "KVM_GET_ONE_REG",
        "bridge_input_resource": "fd_vcpu",
        "bridge_output_resource": None,
    },
    "KVM_RUN": {
        "syz_name": "ioctl$KVM_RUN",
        "event": "use",
        "constant_name": "KVM_RUN",
        "bridge_input_resource": "fd_vcpu",
        "bridge_output_resource": None,
    },
}

KNOWN_KVM_TEMPLATE_FAMILIES: tuple[str, ...] = (
    "openat$KVM",
    "KVM_CREATE_VM",
    "KVM_CREATE_VCPU",
    "KVM_ARM_VCPU_INIT",
    "KVM_SET_ONE_REG",
    "KVM_GET_ONE_REG",
    "KVM_RUN",
    "KVM_CREATE_DEVICE",
    "KVM_SET_DEVICE_ATTR",
    "KVM_IRQ_LINE",
)

SUPPORTED_STRUCT_NAMES = {"kvm_vcpu_init", "kvm_one_reg"}
SUPPORTED_CONSTANT_NAMES = {
    "AT_FDCWD",
    "KVM_CREATE_VM",
    "KVM_CREATE_VCPU",
    "KVM_ARM_VCPU_INIT",
    "KVM_SET_ONE_REG",
    "KVM_GET_ONE_REG",
    "KVM_RUN",
    "KVM_ARM_TARGET_GENERIC_V8",
}

INTEGER_SIZES = {
    "bool8": 1,
    "bool16": 2,
    "bool32": 4,
    "bool64": 8,
    "int8": 1,
    "int16": 2,
    "int32": 4,
    "int64": 8,
    "intptr": 8,
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def bridge_family_from_template_call(call_text: str) -> str | None:
    for family in KNOWN_KVM_TEMPLATE_FAMILIES:
        if family in call_text:
            return family
    return None


def bridge_family_from_syz_name(syz_name: str) -> str | None:
    for family, metadata in SUPPORTED_KVM_WITNESS_FAMILIES.items():
        if metadata["syz_name"] == syz_name:
            return family
    return None


def split_top_level_items(text: str, delimiter: str = ",") -> list[str]:
    items: list[str] = []
    current: list[str] = []
    bracket_depth = 0
    brace_depth = 0
    paren_depth = 0
    in_string = False
    escape = False

    for char in text:
        if in_string:
            current.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            current.append(char)
            continue
        if char == "[":
            bracket_depth += 1
        elif char == "]":
            bracket_depth -= 1
        elif char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth -= 1
        elif char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth -= 1

        if (
            char == delimiter
            and bracket_depth == 0
            and brace_depth == 0
            and paren_depth == 0
        ):
            item = "".join(current).strip()
            if item:
                items.append(item)
            current = []
            continue

        current.append(char)

    tail = "".join(current).strip()
    if tail:
        items.append(tail)
    return items


def _extract_balanced_parentheses(text: str) -> tuple[str, str]:
    depth = 1
    body: list[str] = []
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return "".join(body), text[index + 1 :]
        body.append(char)
    raise ValueError(f"unbalanced parentheses in signature fragment: {text}")


def _parse_signature(line: str) -> tuple[str, list[dict[str, str]], str | None]:
    name, remainder = line.split("(", 1)
    arg_body, tail = _extract_balanced_parentheses(remainder)
    args: list[dict[str, str]] = []
    for arg in split_top_level_items(arg_body):
        arg_parts = arg.strip().split(None, 1)
        if len(arg_parts) != 2:
            raise ValueError(f"bad syscall argument fragment: {arg}")
        args.append({"name": arg_parts[0], "type": arg_parts[1]})
    ret_type = tail.strip() or None
    return name.strip(), args, ret_type


def _parse_const_value(raw_value: str, arch: str) -> int:
    pieces = [piece.strip() for piece in raw_value.split(",") if piece.strip()]
    default_value = pieces[0]
    for piece in pieces[1:]:
        if ":" not in piece:
            continue
        parts = [part.strip() for part in piece.split(":")]
        value = parts[-1]
        if arch in parts[:-1] and value != "???":
            return int(value, 0)
    if default_value == "???":
        raise ValueError(f"missing {arch} constant value")
    return int(default_value, 0)


def _parse_field_type_size(type_expr: str, struct_sizes: dict[str, int]) -> int:
    if type_expr in INTEGER_SIZES:
        return INTEGER_SIZES[type_expr]
    if type_expr in struct_sizes:
        return struct_sizes[type_expr]
    if type_expr == "fd" or type_expr.startswith("fd_"):
        return 8
    if type_expr.startswith("ptr64[") or type_expr.startswith("vma64"):
        return 8
    if type_expr.startswith("const[") or type_expr.startswith("flags[") or type_expr.startswith("len["):
        inner = type_expr[type_expr.find("[") + 1 : -1]
        parts = split_top_level_items(inner)
        base_type = parts[-1] if parts else "intptr"
        base_type = base_type.split(":", 1)[0]
        return _parse_field_type_size(base_type, struct_sizes)
    if type_expr.startswith("array["):
        inner = type_expr[type_expr.find("[") + 1 : -1]
        elem_type, count_text = split_top_level_items(inner)
        return _parse_field_type_size(elem_type, struct_sizes) * int(count_text, 0)
    raise ValueError(f"unsupported field type in supported KVM struct: {type_expr}")


def _parse_supported_structs(lines: list[str]) -> dict[str, dict[str, Any]]:
    parsed: dict[str, dict[str, Any]] = {}
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line.endswith("{"):
            index += 1
            continue
        struct_name = line[:-1].strip()
        if struct_name not in SUPPORTED_STRUCT_NAMES:
            index += 1
            continue

        fields: list[dict[str, str]] = []
        index += 1
        while index < len(lines):
            field_line = lines[index].split("#", 1)[0].strip()
            if field_line.startswith("}"):
                break
            if field_line:
                field_line = re.sub(r"\s+\((?:in|out|inout)\)\s*$", "", field_line)
                field_parts = field_line.split()
                fields.append({"name": field_parts[0], "type": "".join(field_parts[1:])})
            index += 1

        if index >= len(lines):
            raise ValueError(f"unterminated struct definition for {struct_name}")
        parsed[struct_name] = {"fields": fields}
        index += 1

    struct_sizes: dict[str, int] = {}
    for struct_name, payload in parsed.items():
        struct_sizes[struct_name] = sum(
            _parse_field_type_size(field["type"], struct_sizes) for field in payload["fields"]
        )
    for struct_name, size in struct_sizes.items():
        parsed[struct_name]["size"] = size
    return parsed


def _load_description_files(syzkaller_root: Path) -> tuple[list[str], list[str]]:
    dev_kvm_path = syzkaller_root / "sys" / "linux" / "dev_kvm.txt"
    const_path = syzkaller_root / "sys" / "linux" / "dev_kvm.txt.const"
    if not dev_kvm_path.is_file():
        raise FileNotFoundError(f"missing syzkaller KVM description file: {dev_kvm_path}")
    if not const_path.is_file():
        raise FileNotFoundError(f"missing syzkaller KVM const file: {const_path}")
    return (
        dev_kvm_path.read_text(encoding="utf-8").splitlines(),
        const_path.read_text(encoding="utf-8").splitlines(),
    )


def find_syzkaller_root(explicit_root: str | Path | None = None) -> Path:
    candidates: list[Path] = []
    if explicit_root is not None:
        candidates.append(Path(explicit_root))
    env_root = os.environ.get(SYZ_ROOT_ENV)
    if env_root:
        candidates.append(Path(env_root))

    mock_target = repo_root() / "mock" / "target"
    for build_dir in ("release", "debug"):
        build_root = mock_target / build_dir / "build"
        if build_root.is_dir():
            candidates.extend(sorted(build_root.glob("syz_wrapper-*/out/syzkaller-*")))

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if (resolved / "sys" / "linux" / "dev_kvm.txt").is_file():
            return resolved

    raise FileNotFoundError(
        "unable to locate syzkaller root with sys/linux/dev_kvm.txt; "
        f"set {SYZ_ROOT_ENV} or pass --syz-root"
    )


@lru_cache(maxsize=None)
def harvest_kvm_descriptions(syzkaller_root: str | Path | None = None, arch: str = "arm64") -> dict[str, Any]:
    root = find_syzkaller_root(syzkaller_root)
    description_lines, const_lines = _load_description_files(root)
    structs = _parse_supported_structs(description_lines)

    constants: dict[str, int] = {}
    for line in const_lines:
        if "=" not in line or line.startswith("#"):
            continue
        name, raw_value = [part.strip() for part in line.split("=", 1)]
        if name in SUPPORTED_CONSTANT_NAMES:
            constants[name] = _parse_const_value(raw_value, arch)

    missing_constants = sorted(SUPPORTED_CONSTANT_NAMES.difference(constants))
    if missing_constants:
        raise ValueError(f"missing required KVM constants: {', '.join(missing_constants)}")

    syscalls: dict[str, dict[str, Any]] = {}
    supported_syz_names = {str(spec["syz_name"]) for spec in SUPPORTED_KVM_WITNESS_FAMILIES.values()}
    for raw_line in description_lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "(" not in line or line.endswith("{"):
            continue
        syscall_name = line.split("(", 1)[0]
        if syscall_name not in supported_syz_names:
            continue
        parsed_name, args, ret_type = _parse_signature(line)
        family = bridge_family_from_syz_name(parsed_name)
        if family is None:
            continue
        struct_arg = None
        if len(args) >= 3:
            struct_match = re.search(r",\s*([A-Za-z0-9_]+)\]$", args[2]["type"])
            if struct_match is not None:
                struct_arg = struct_match.group(1)
        syscalls[family] = {
            "bridge_family": family,
            "syz_name": parsed_name,
            "event": SUPPORTED_KVM_WITNESS_FAMILIES[family]["event"],
            "constant_name": SUPPORTED_KVM_WITNESS_FAMILIES[family]["constant_name"],
            "bridge_input_resource": SUPPORTED_KVM_WITNESS_FAMILIES[family]["bridge_input_resource"],
            "bridge_output_resource": SUPPORTED_KVM_WITNESS_FAMILIES[family]["bridge_output_resource"],
            "arg_names": [arg["name"] for arg in args],
            "arg_types": [arg["type"] for arg in args],
            "input_resource_type": args[0]["type"] if args and args[0]["type"].startswith("fd_") else None,
            "output_resource_type": ret_type if isinstance(ret_type, str) and ret_type.startswith("fd_") else None,
            "struct_arg": struct_arg,
            "signature": line,
        }

    missing_syscalls = sorted(set(SUPPORTED_KVM_WITNESS_FAMILIES).difference(syscalls))
    if missing_syscalls:
        raise ValueError(f"missing required KVM syscall descriptions: {', '.join(missing_syscalls)}")

    for family, syscall in syscalls.items():
        struct_arg = syscall.get("struct_arg")
        if isinstance(struct_arg, str) and struct_arg not in structs:
            raise ValueError(f"missing required struct description for {family}: {struct_arg}")

    return {
        "arch": arch,
        "syzkaller_root": str(root),
        "constants": constants,
        "structs": structs,
        "syscalls": syscalls,
    }
