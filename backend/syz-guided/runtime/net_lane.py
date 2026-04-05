#!/usr/bin/env python3
"""Live arm64 QEMU nf_tables validation lane.

Execution order is intentionally narrow and debug-friendly:
  1. strict preflight against the host and a real guest boot
  2. single-seed validation
  3. four-seed validation
  4. short bounded campaign
  5. optional extended campaign

The lane emits exact per-seed artifacts, layered evidence, crash repro results,
and manual known-bug hygiene artifacts before novelty is implied.
"""

from __future__ import annotations

import argparse
import gzip
import json
import pathlib
import shlex
import struct
import subprocess
import sys
import time
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from orchestrator.score import _score_phase_progress, _score_prefix, _score_resource_chain
from pack_registry import resolve_target_manifest
from triage.kernel_crash import parse_kernel_crash
from triage.match_candidate import match_crash
from triage.net_symbols import classify_crash_subsystem_relevance, enrich_crash_match
from triage.net_verdict import (
    build_candidate_evidence,
    build_crash_evidence,
    build_execution_evidence,
    classify_net_runtime_verdict,
    classify_reproducibility,
)
from triage.parse_kasan import parse_kasan_report
from triage.report import build_triage_report
from vm_validator.prog_injector import build_inject_cmd, build_scp_cmd
from vm_validator.vm_runner import boot_vm, shutdown_vm
from runtime.net_lab import (
    build_blocker_report,
    build_kernel_provenance,
    build_lab_run_bundle,
    build_source_frame_summary,
    classify_lab_net_state,
    rank_net_files,
    rank_net_seeds,
)

REQUIRED_KERNEL_CONFIGS = [
    "CONFIG_KASAN=y",
    "CONFIG_KCOV=y",
    "CONFIG_DEBUG_INFO=y",
    "CONFIG_DEBUG_FS=y",
    "CONFIG_KCOV_INSTRUMENT_ALL=y",
]
REQUIRED_KERNEL_CONFIG_ALTERNATIVES = {
    "CONFIG_NETFILTER": ["CONFIG_NETFILTER=y", "CONFIG_NETFILTER=m"],
    "CONFIG_NF_TABLES": ["CONFIG_NF_TABLES=y", "CONFIG_NF_TABLES=m"],
}
REQUIRED_NET_MODULES = ["nfnetlink", "nf_tables"]
STAGE_SPECS = [
    ("single-seed-validation", 1),
    ("four-seed-validation", 4),
    ("short-bounded-campaign", None),
]
DEFAULT_PROOF_MODE = "off"
PROOF_MODES = {"off", "controlled", "organic"}
SEED_RESULT_CLASSES = {
    "completed-no-crash",
    "completed-crash",
    "timed-out",
    "stalled",
    "setup-failure",
    "guest-exec-failure",
    "target-not-reached",
}
GUEST_RUNTIME_DIR = "/tmp/madelin-net-runtime"
FALLBACK_GUEST_RUNTIME_DIR = "/var/tmp/madelin-net-runtime"
DEFAULT_GUEST_SYZ_EXECPROG = f"{GUEST_RUNTIME_DIR}/syz-execprog"
DEFAULT_GUEST_SYZ_EXECUTOR = f"{GUEST_RUNTIME_DIR}/syz-executor"
DEFAULT_GUEST_SEED_PATH = f"{GUEST_RUNTIME_DIR}/seed.prog"
DEFAULT_GUEST_COVER_PATH = f"{GUEST_RUNTIME_DIR}/seed.cover"
DEFAULT_GUEST_EXTRA_APPEND = (
    "systemd.unit=multi-user.target "
    "fsck.mode=skip "
    "systemd.default_timeout_start_sec=15s "
    "systemd.mask=serial-getty@ttyAMA0.service "
    "systemd.mask=systemd-networkd-wait-online.service "
    "systemd.mask=multipathd.service "
    "systemd.mask=boot.mount "
    "systemd.mask=boot-efi.mount"
)
DEFAULT_SSH_PROBE_TIMEOUT = 20
DEFAULT_PROBE_RETRIES = 3
LARGE_GUEST_COPY_THRESHOLD_BYTES = 8 * 1024 * 1024


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    with open(path) as f:
        return json.load(f)


def _write_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def _write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_progress(
    out_dir: pathlib.Path,
    *,
    stage_index: int,
    stage_total: int,
    stage_name: str,
    substage: str,
    status: str,
    seed: str | None = None,
    current: int | None = None,
    total: int | None = None,
    elapsed_sec: float | None = None,
    timeout_sec: int | None = None,
    detail: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
        "stage_index": stage_index,
        "stage_total": stage_total,
        "stage_name": stage_name,
        "substage": substage,
        "status": status,
    }
    if seed is not None:
        payload["seed"] = seed
    if current is not None:
        payload["current"] = current
    if total is not None:
        payload["total"] = total
    if elapsed_sec is not None:
        payload["elapsed_sec"] = round(elapsed_sec, 3)
    if timeout_sec is not None:
        payload["timeout_sec"] = timeout_sec
    if detail is not None:
        payload["detail"] = detail
    _write_json(out_dir / "logs" / "progress.json", payload)


def _update_preflight_progress(
    out_dir: pathlib.Path,
    *,
    host_checks: list[dict[str, Any]],
    guest_checks: list[dict[str, Any]],
    environment: dict[str, Any],
    stage: str,
) -> None:
    payload = {
        "stage": stage,
        "host_checks": host_checks,
        "guest_checks": guest_checks,
        "environment": environment,
    }
    _write_json(out_dir / "preflight_progress.json", payload)


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.localtime())


def _runtime_paths(runtime_dir: str) -> dict[str, str]:
    return {
        "runtime_dir": runtime_dir,
        "seed_path": f"{runtime_dir}/seed.prog",
        "cover_path": f"{runtime_dir}/seed.cover",
    }


def _should_retry_runtime_dir(copy_result: dict[str, Any]) -> bool:
    text = "\n".join(
        str(copy_result.get(field, ""))
        for field in ["error", "stderr", "scp_error", "scp_stderr"]
    ).lower()
    return "no such file or directory" in text or "directory nonexistent" in text


def _seed_manifest_order(seeds_dir: pathlib.Path) -> list[str]:
    manifest_path = seeds_dir / "seed_manifest.json"
    if not manifest_path.exists():
        return []
    try:
        manifest = _load_json(manifest_path)
    except Exception:
        return []
    order: list[str] = []
    for seed in manifest.get("seeds", []):
        if isinstance(seed, dict) and isinstance(seed.get("name"), str):
            order.append(seed["name"])
    return order


def _ordered_seed_paths(seeds_dir: pathlib.Path, *, proof_mode: str) -> list[pathlib.Path]:
    by_name = {path.name: path for path in seeds_dir.glob("*.prog")}
    manifest_order = _seed_manifest_order(seeds_dir)
    ordered = [by_name[name] for name in manifest_order if name in by_name]
    remaining = sorted(path for name, path in by_name.items() if name not in set(manifest_order))
    seeds = ordered + remaining
    if proof_mode == "controlled":
        preferred = [
            "seed_delete_dump.prog",
            "seed_dump_delete.prog",
            "seed_update_dump_delete.prog",
        ]
        rank = {name: idx for idx, name in enumerate(preferred)}
        order_lookup = {name: idx for idx, name in enumerate(manifest_order)}
        seeds = sorted(
            seeds,
            key=lambda path: (
                rank.get(path.name, len(preferred)),
                order_lookup.get(path.name, 10_000),
                path.name,
            ),
        )
    return seeds


def _proof_manifest(
    *,
    proof_mode: str,
    kernel: pathlib.Path,
    disk_image: pathlib.Path,
    guest_syz_execprog_path: str,
    guest_syz_executor_path: str,
    seed: pathlib.Path | None,
    timeout_sec: int,
    threaded: bool,
    procs: int,
    proof_kernel_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    repro_command = None
    if seed is not None:
        repro_command = (
            f"{guest_syz_execprog_path} -executor={guest_syz_executor_path} -repeat=0 -procs={procs} "
            f"-threaded={1 if threaded else 0} -coverfile={DEFAULT_GUEST_COVER_PATH} {DEFAULT_GUEST_SEED_PATH}"
        )
    return {
        "proof_mode": proof_mode,
        "kernel": str(kernel),
        "disk_image": str(disk_image),
        "guest_syz_execprog_path": guest_syz_execprog_path,
        "guest_syz_executor_path": guest_syz_executor_path,
        "seed": None if seed is None else seed.name,
        "timeout_sec": timeout_sec,
        "threaded": threaded,
        "procs": procs,
        "repro_command": repro_command,
        "proof_kernel_meta": proof_kernel_meta,
    }


def _canonical_seed_calls(seed_path: pathlib.Path, manifest: dict[str, Any]) -> list[str]:
    reverse: dict[str, str] = {}
    for canonical_call, syz_line in manifest.get("syz_call_map", {}).items():
        if not isinstance(canonical_call, str) or not isinstance(syz_line, str):
            continue
        normalized = syz_line.strip()
        if "=" in normalized:
            normalized = normalized.split("=", 1)[1].strip()
        call_name = normalized.split("(", 1)[0].strip()
        if call_name and call_name not in reverse:
            reverse[call_name] = canonical_call

    canonical_calls: list[str] = []
    for line in seed_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            stripped = stripped.split("=", 1)[1].strip()
        call_name = stripped.split("(", 1)[0].strip()
        canonical_calls.append(reverse.get(call_name, call_name))
    return canonical_calls


def _run_cmd(cmd: list[str], timeout_sec: int) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
        return {
            "ok": proc.returncode == 0,
            "timed_out": False,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "duration_sec": round(time.monotonic() - started, 3),
            "error": None if proc.returncode == 0 else f"rc={proc.returncode}",
            "cmd": cmd,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "timed_out": True,
            "returncode": None,
            "stdout": exc.stdout if isinstance(exc.stdout, str) else "",
            "stderr": exc.stderr if isinstance(exc.stderr, str) else "",
            "duration_sec": round(time.monotonic() - started, 3),
            "error": f"timeout after {timeout_sec}s",
            "cmd": cmd,
        }
    except OSError as exc:
        return {
            "ok": False,
            "timed_out": False,
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "duration_sec": round(time.monotonic() - started, 3),
            "error": str(exc),
            "cmd": cmd,
        }


def _phase_name(progress: float) -> str:
    if progress >= 1.0:
        return "trigger"
    if progress >= 0.66:
        return "configure"
    if progress >= 0.33:
        return "bootstrap"
    return "unknown"


def _read_elf_machine(path: pathlib.Path) -> int | None:
    data = path.read_bytes()[:64]
    if len(data) < 20 or data[:4] != b"\x7fELF":
        return None
    endian = "<" if data[5] == 1 else ">" if data[5] == 2 else None
    if not endian:
        return None
    return struct.unpack(f"{endian}H", data[18:20])[0]


def _host_check(path: pathlib.Path, label: str) -> dict[str, Any]:
    if not path.exists():
        return {"ok": False, "name": label, "error": f"{label} not found: {path}"}
    if not path.is_file():
        return {"ok": False, "name": label, "error": f"{label} is not a regular file: {path}"}
    if path.stat().st_size == 0:
        return {"ok": False, "name": label, "error": f"{label} is empty: {path}"}
    return {"ok": True, "name": label, "path": str(path), "size_bytes": path.stat().st_size}


def _host_cmd_check(name: str) -> dict[str, Any]:
    result = _run_cmd(["sh", "-lc", f"command -v {shlex.quote(name)} >/dev/null 2>&1 && command -v {shlex.quote(name)}"], 5)
    if not result["ok"]:
        return {"ok": False, "name": name, "error": f"required host command not found: {name}"}
    return {"ok": True, "name": name, "path": result["stdout"].strip()}


def _check_arm64_binary(path: pathlib.Path, label: str) -> dict[str, Any]:
    base = _host_check(path, label)
    if not base["ok"]:
        return base
    machine = _read_elf_machine(path)
    if machine is None:
        return {"ok": False, "name": label, "error": f"{label} is not a readable ELF binary: {path}"}
    if machine != 183:
        return {
            "ok": False,
            "name": label,
            "error": f"{label} must be a linux/arm64 ELF binary for guest execution; got e_machine={machine} at {path}",
        }
    return {**base, "machine": machine, "target": "linux/arm64"}


def _check_guest_arm64_binary(
    ssh_port: int,
    ssh_key: pathlib.Path,
    remote_path: str,
    label: str,
) -> dict[str, Any]:
    remote_q = shlex.quote(remote_path)
    cmd = f"""
set -eu
test -f {remote_q}
python3 -c 'import pathlib, struct, sys; path = pathlib.Path(sys.argv[1]); data = path.read_bytes()[:64]; assert len(data) >= 20 and data[:4] == b"\\x7fELF", "not-elf"; endian = "<" if data[5] == 1 else ">" if data[5] == 2 else None; assert endian is not None, "bad-elf-endian"; machine = struct.unpack(f"{{endian}}H", data[18:20])[0]; assert machine == 183, f"bad-machine={{machine}}"; print(machine)' {remote_q}
""".strip()
    result = _guest_cmd_retry(ssh_port, ssh_key, cmd, timeout_sec=20)
    if not result["ok"]:
        return {
            "ok": False,
            "name": label,
            "path": remote_path,
            "error": f"{label} is not a usable linux/arm64 ELF binary at {remote_path}: {result.get('error') or result.get('stderr', '').strip()}",
        }
    return {
        "ok": True,
        "name": label,
        "path": remote_path,
        "machine": 183,
        "target": "linux/arm64",
        "source": "guest-resident",
    }


def _guest_file_size(
    ssh_port: int,
    ssh_key: pathlib.Path,
    remote_path: str,
    *,
    timeout_sec: int = 20,
) -> dict[str, Any]:
    remote_q = shlex.quote(remote_path)
    cmd = f"test -f {remote_q} && wc -c < {remote_q}"
    result = _guest_cmd_retry(ssh_port, ssh_key, cmd, timeout_sec=timeout_sec)
    if not result["ok"]:
        return {"ok": False, "error": result.get("error"), "attempts": result.get("attempts", [])}
    try:
        size = int((result.get("stdout") or "").strip())
    except ValueError:
        return {"ok": False, "error": f"unable to parse remote size for {remote_path}", "attempts": result.get("attempts", [])}
    return {"ok": True, "size_bytes": size, "attempts": result.get("attempts", [])}


def _guest_binary_reusable(
    *,
    host_path: pathlib.Path | None,
    remote_path: str,
    ssh_port: int,
    ssh_key: pathlib.Path,
    label: str,
) -> dict[str, Any]:
    arch = _check_guest_arm64_binary(ssh_port, ssh_key, remote_path, label)
    if not arch["ok"]:
        return {"ok": False, "reason": arch.get("error"), "arch_check": arch}
    if host_path is None:
        return {"ok": True, "reason": "guest-resident binary validated", "arch_check": arch}
    size = _guest_file_size(ssh_port, ssh_key, remote_path)
    expected_size = host_path.stat().st_size
    if not size["ok"]:
        return {"ok": False, "reason": size.get("error"), "arch_check": arch, "size_check": size}
    if size["size_bytes"] != expected_size:
        return {
            "ok": False,
            "reason": f"remote size {size['size_bytes']} does not match host size {expected_size}",
            "arch_check": arch,
            "size_check": size,
        }
    return {
        "ok": True,
        "reason": "guest binary matches host size and architecture",
        "arch_check": arch,
        "size_check": size,
        "expected_size": expected_size,
    }


def _ssh_cmd(ssh_port: int, ssh_key: pathlib.Path) -> list[str]:
    return build_inject_cmd(ssh_port=ssh_port, ssh_key=ssh_key)


def _guest_cmd(
    ssh_port: int,
    ssh_key: pathlib.Path,
    command: str,
    *,
    timeout_sec: int = 30,
) -> dict[str, Any]:
    cmd = _ssh_cmd(ssh_port, ssh_key) + [f"sh -c {shlex.quote(command)}"]
    return _run_cmd(cmd, timeout_sec)


def _guest_cmd_retry(
    ssh_port: int,
    ssh_key: pathlib.Path,
    command: str,
    *,
    timeout_sec: int,
    attempts: int = DEFAULT_PROBE_RETRIES,
    retry_delay_sec: float = 1.0,
) -> dict[str, Any]:
    last_result: dict[str, Any] | None = None
    tries: list[dict[str, Any]] = []
    for attempt in range(1, max(attempts, 1) + 1):
        result = _guest_cmd(ssh_port, ssh_key, command, timeout_sec=timeout_sec)
        result = {**result, "attempt": attempt}
        tries.append({
            "attempt": attempt,
            "ok": result["ok"],
            "timed_out": result.get("timed_out", False),
            "duration_sec": result.get("duration_sec"),
            "error": result.get("error"),
        })
        last_result = result
        if result["ok"]:
            return {**result, "attempts": tries}
        if not result.get("timed_out"):
            break
        if attempt < attempts:
            time.sleep(retry_delay_sec)
    if last_result is None:
        last_result = {
            "ok": False,
            "timed_out": False,
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "duration_sec": 0.0,
            "error": "probe did not run",
            "cmd": [],
        }
    return {**last_result, "attempts": tries}


def _copy_to_guest(local_path: pathlib.Path, remote_path: str, ssh_port: int, ssh_key: pathlib.Path) -> dict[str, Any]:
    parent_dir = pathlib.PurePosixPath(remote_path).parent.as_posix()
    mkdir = _guest_cmd_retry(ssh_port, ssh_key, f"mkdir -p {shlex.quote(parent_dir)}", timeout_sec=30)
    if not mkdir["ok"]:
        return {
            "ok": False,
            "returncode": mkdir.get("returncode"),
            "stdout": mkdir.get("stdout", ""),
            "stderr": mkdir.get("stderr", ""),
            "duration_sec": mkdir.get("duration_sec", 0.0),
            "error": f"failed to create guest staging directory {parent_dir}: {mkdir.get('error')}",
            "cmd": mkdir.get("cmd", []),
            "attempts": mkdir.get("attempts", []),
            "method": "mkdir",
        }

    remote_q = shlex.quote(remote_path)
    ssh_cmd = _ssh_cmd(ssh_port, ssh_key) + [f"sh -c {shlex.quote(f'cat > {remote_q}')}" ]
    file_size = local_path.stat().st_size

    def _stream_copy(
        scp_result: dict[str, Any] | None,
        *,
        fallback_from: str | None = None,
        compressed: bool = False,
    ) -> dict[str, Any]:
        started = time.monotonic()
        stream_cmd = ssh_cmd
        stream_input: bytes | None = None
        method = "ssh-cat"
        if compressed:
            stream_cmd = _ssh_cmd(ssh_port, ssh_key) + [
                f"sh -c {shlex.quote(f'python3 -c \"import gzip, pathlib, sys; pathlib.Path(sys.argv[1]).write_bytes(gzip.decompress(sys.stdin.buffer.read()))\" {remote_q}') }"
            ]
            stream_input = gzip.compress(local_path.read_bytes(), compresslevel=1)
            method = "ssh-cat-gzip"
        try:
            if compressed:
                proc = subprocess.run(
                    stream_cmd,
                    input=stream_input,
                    capture_output=True,
                    timeout=180,
                )
            else:
                with open(local_path, "rb") as src:
                    proc = subprocess.run(
                        stream_cmd,
                        stdin=src,
                        capture_output=True,
                        timeout=180,
                    )
            streamed = {
                "ok": proc.returncode == 0,
                "timed_out": False,
                "returncode": proc.returncode,
                "stdout": proc.stdout.decode(errors="replace"),
                "stderr": proc.stderr.decode(errors="replace"),
                "duration_sec": round(time.monotonic() - started, 3),
                "error": None if proc.returncode == 0 else f"stream-copy rc={proc.returncode}",
                "cmd": stream_cmd,
                "method": method,
            }
            if fallback_from:
                streamed["fallback_from"] = fallback_from
            if scp_result is not None:
                streamed["scp_stdout"] = scp_result.get("stdout", "")
                streamed["scp_stderr"] = scp_result.get("stderr", "")
                streamed["scp_error"] = scp_result.get("error")
            return streamed
        except subprocess.TimeoutExpired as exc:
            return {
                "ok": False,
                "timed_out": True,
                "returncode": None,
                "stdout": exc.stdout.decode(errors="replace") if isinstance(exc.stdout, (bytes, bytearray)) else (exc.stdout or ""),
                "stderr": exc.stderr.decode(errors="replace") if isinstance(exc.stderr, (bytes, bytearray)) else (exc.stderr or ""),
                "duration_sec": round(time.monotonic() - started, 3),
                "error": "stream-copy timeout after 180s",
                "cmd": stream_cmd,
                "method": method,
                "fallback_from": fallback_from,
                "scp_stdout": "" if scp_result is None else scp_result.get("stdout", ""),
                "scp_stderr": "" if scp_result is None else scp_result.get("stderr", ""),
                "scp_error": None if scp_result is None else scp_result.get("error"),
            }
        except OSError as exc:
            return {
                "ok": False,
                "timed_out": False,
                "returncode": None,
                "stdout": "",
                "stderr": "",
                "duration_sec": round(time.monotonic() - started, 3),
                "error": f"stream-copy failed: {exc}",
                "cmd": stream_cmd,
                "method": method,
                "fallback_from": fallback_from,
                "scp_stdout": "" if scp_result is None else scp_result.get("stdout", ""),
                "scp_stderr": "" if scp_result is None else scp_result.get("stderr", ""),
                "scp_error": None if scp_result is None else scp_result.get("error"),
            }

    if file_size >= LARGE_GUEST_COPY_THRESHOLD_BYTES:
        return _stream_copy(None, compressed=True)

    cmd = build_scp_cmd(local_path=local_path, remote_path=remote_path, ssh_port=ssh_port, ssh_key=ssh_key)
    scp_result = _run_cmd(cmd, 45)
    scp_result["method"] = "scp"
    if scp_result["ok"]:
        return scp_result

    return _stream_copy(scp_result, fallback_from="scp")


def _fetch_from_guest(remote_path: str, local_path: pathlib.Path, ssh_port: int, ssh_key: pathlib.Path) -> dict[str, Any]:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_scp_cmd(local_path=local_path, remote_path=remote_path, ssh_port=ssh_port, ssh_key=ssh_key)
    cmd[-2], cmd[-1] = cmd[-1], cmd[-2]
    return _run_cmd(cmd, 120)


def _boot_guest(
    *,
    kernel: pathlib.Path,
    disk_image: pathlib.Path,
    ssh_key: pathlib.Path,
    ssh_port: int,
    console_log: pathlib.Path,
    boot_timeout: int,
    guest_extra_append: str,
) -> dict[str, Any]:
    boot = boot_vm(
        kernel=kernel,
        disk_image=disk_image,
        ssh_port=ssh_port,
        console_log=console_log,
        boot_timeout=boot_timeout,
        ssh_key=ssh_key,
        extra_append=guest_extra_append,
    )
    if not boot["ok"]:
        if boot.get("process") is not None:
            shutdown_vm(boot["process"], ssh_port=ssh_port, ssh_key=ssh_key)
        return boot
    return boot


def _probe_guest_kernel_config(
    ssh_port: int,
    ssh_key: pathlib.Path,
    required: list[str],
    alternatives: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    wanted = list(required)
    for choices in (alternatives or {}).values():
        wanted.extend(choices)
    pattern = "|".join(shlex.quote(item) for item in wanted)
    cmd = f"""
set -e
if [ -r /proc/config.gz ]; then
  echo CONFIG_PATH=/proc/config.gz
  gzip -dc /proc/config.gz | grep -E '^({pattern})$' || true
elif [ -r /boot/config-$(uname -r) ]; then
  echo CONFIG_PATH=/boot/config-$(uname -r)
  grep -E '^({pattern})$' /boot/config-$(uname -r) || true
elif [ -r /lib/modules/$(uname -r)/config ]; then
  echo CONFIG_PATH=/lib/modules/$(uname -r)/config
  grep -E '^({pattern})$' /lib/modules/$(uname -r)/config || true
else
  exit 42
fi
""".strip()
    result = _guest_cmd(ssh_port, ssh_key, cmd, timeout_sec=20)
    if result["returncode"] == 42:
        return {"ok": False, "error": "guest kernel config is unavailable; expose /proc/config.gz or /boot/config-$(uname -r)"}
    if not result["ok"]:
        return {"ok": False, "error": result.get("error") or result.get("stderr", "kernel config probe failed")}
    lines = result["stdout"].splitlines()
    config_path = None
    if lines and lines[0].startswith("CONFIG_PATH="):
        config_path = lines[0].split("=", 1)[1].strip()
        lines = lines[1:]
    return {"ok": True, "config_text": "\n".join(lines), "config_path": config_path}


def _parse_config_requirements(
    config_text: str,
    required: list[str],
    alternatives: dict[str, list[str]] | None = None,
) -> tuple[list[str], list[str]]:
    present: list[str] = []
    missing: list[str] = []
    for item in required:
        if item in config_text:
            present.append(item)
        else:
            missing.append(item)
    for name, choices in (alternatives or {}).items():
        hit = next((choice for choice in choices if choice in config_text), None)
        if hit:
            present.append(hit)
        else:
            missing.append(name)
    return present, missing


def _prepare_guest_runtime_environment(ssh_port: int, ssh_key: pathlib.Path) -> dict[str, Any]:
    cmd = """
set -eu
mkdir -p /tmp
mkdir -p /var/tmp
test -w /tmp || mount -o remount,rw / >/dev/null 2>&1 || mount -o remount,rw /dev/root / >/dev/null 2>&1 || true
mkdir -p /proc /sys /sys/kernel /sys/kernel/debug /dev /dev/pts /run
mountpoint -q /proc || mount -t proc proc /proc || true
mountpoint -q /sys || mount -t sysfs sysfs /sys || true
mountpoint -q /dev/pts || mount -t devpts devpts /dev/pts || true
mountpoint -q /sys/kernel/debug || mount -t debugfs debugfs /sys/kernel/debug || true
mkdir -p /tmp/madelin-net-runtime
mkdir -p /var/tmp/madelin-net-runtime
if command -v ip >/dev/null 2>&1; then
  ip link set lo up || true
  ip link set eth0 up || true
  ip addr show dev eth0 | grep -q '10.0.2.15/' || ip addr add 10.0.2.15/24 dev eth0 || true
  ip route show default | grep -q . || ip route replace default via 10.0.2.2 dev eth0 || true
fi
cat /proc/cmdline >/dev/null
""".strip()
    return _guest_cmd(ssh_port, ssh_key, cmd, timeout_sec=45)


def _check_guest_execprog_coverfile_support(ssh_port: int, ssh_key: pathlib.Path, guest_syz_execprog_path: str) -> dict[str, Any]:
    remote_q = shlex.quote(guest_syz_execprog_path)
    cmd = f"grep -a -m1 -o 'coverfile' {remote_q} || true"
    result = _guest_cmd_retry(ssh_port, ssh_key, cmd, timeout_sec=20)
    return {
        "ok": result["ok"] and "coverfile" in result.get("stdout", ""),
        "excerpt": result.get("stdout", "").strip(),
        "attempts": result.get("attempts", []),
        "error": None if result["ok"] and "coverfile" in result.get("stdout", "") else "syz-execprog in guest does not advertise -coverfile; update syzkaller build so KCOV artifacts can be captured",
    }


def _check_guest_modules(ssh_port: int, ssh_key: pathlib.Path, modules: list[str]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for module in modules:
        cmd = f"""
if [ -d /sys/module/{module} ]; then
  echo loaded
elif command -v modprobe >/dev/null 2>&1 && modprobe {module} >/dev/null 2>&1; then
  echo modprobed
else
  exit 1
fi
""".strip()
        result = _guest_cmd(ssh_port, ssh_key, cmd, timeout_sec=15)
        if result["ok"]:
            checks.append({"ok": True, "name": f"module:{module}", "state": result["stdout"].strip() or "loaded"})
        else:
            checks.append({
                "ok": False,
                "name": f"module:{module}",
                "error": f"guest is missing required module/feature {module}; build it in or make modprobe succeed",
            })
    return checks


def _check_guest_net_features(
    ssh_port: int,
    ssh_key: pathlib.Path,
    config_text: str,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    feature_map = {
        "nfnetlink": ["CONFIG_NETFILTER=y", "CONFIG_NETFILTER=m"],
        "nf_tables": ["CONFIG_NF_TABLES=y", "CONFIG_NF_TABLES=m"],
    }
    for feature, config_markers in feature_map.items():
        if any(marker.endswith("=y") and marker in config_text for marker in config_markers):
            checks.append({
                "ok": True,
                "name": f"feature:{feature}",
                "state": "built-in-config",
            })
            continue
        cmd = f"""
if [ -d /sys/module/{feature} ]; then
  echo loaded
elif command -v modprobe >/dev/null 2>&1 && modprobe {feature} >/dev/null 2>&1; then
  echo modprobed
else
  exit 1
fi
""".strip()
        result = _guest_cmd(ssh_port, ssh_key, cmd, timeout_sec=15)
        if result["ok"]:
            checks.append({"ok": True, "name": f"feature:{feature}", "state": result["stdout"].strip() or "loaded"})
        else:
            checks.append({
                "ok": False,
                "name": f"feature:{feature}",
                "error": f"guest is missing required netfilter feature {feature}; build it in or make modprobe succeed",
            })
    return checks


def run_live_preflight(
    *,
    kernel: pathlib.Path,
    disk_image: pathlib.Path,
    ssh_key: pathlib.Path,
    syz_execprog: pathlib.Path | None,
    syz_executor: pathlib.Path | None,
    out_dir: pathlib.Path,
    ssh_port: int = 10022,
    boot_timeout: int = 300,
    guest_syz_execprog_path: str = DEFAULT_GUEST_SYZ_EXECPROG,
    guest_syz_executor_path: str = DEFAULT_GUEST_SYZ_EXECUTOR,
    guest_extra_append: str = DEFAULT_GUEST_EXTRA_APPEND,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    host_checks = [
        _host_cmd_check("qemu-system-aarch64"),
        _host_cmd_check("ssh"),
        _host_cmd_check("scp"),
        _host_check(kernel, "kernel"),
        _host_check(disk_image, "disk_image"),
        _host_check(ssh_key, "ssh_key"),
    ]
    if syz_execprog is not None:
        host_checks.append(_check_arm64_binary(syz_execprog, "syz_execprog"))
    else:
        host_checks.append({
            "ok": True,
            "name": "syz_execprog",
            "path": guest_syz_execprog_path,
            "source": "guest-resident",
            "note": "preflight will validate the guest-resident syz-execprog instead of staging a host copy",
        })
    if syz_executor is not None:
        host_checks.append(_check_arm64_binary(syz_executor, "syz_executor"))
    else:
        host_checks.append({
            "ok": True,
            "name": "syz_executor",
            "path": guest_syz_executor_path,
            "source": "guest-resident",
            "note": "preflight will validate the guest-resident syz-executor instead of staging a host copy",
        })
    if ssh_key.exists():
        mode = ssh_key.stat().st_mode & 0o777
        if mode & 0o077:
            host_checks.append({
                "ok": False,
                "name": "ssh_key_permissions",
                "error": f"SSH key {ssh_key} has permissions {oct(mode)}; run chmod 600 {ssh_key}",
            })
        else:
            host_checks.append({"ok": True, "name": "ssh_key_permissions", "mode": oct(mode)})

    failed_host = [check for check in host_checks if not check["ok"]]
    if failed_host:
        summary = {
            "ready": False,
            "failure_class": "environment/setup failure",
            "host_checks": host_checks,
            "guest_checks": [],
            "environment": {},
        }
        _update_preflight_progress(out_dir, host_checks=host_checks, guest_checks=[], environment={}, stage="host-checks-failed")
        _write_json(out_dir / "preflight_summary.json", summary)
        return summary

    console_log = out_dir / "boot-console.log"
    boot = _boot_guest(
        kernel=kernel,
        disk_image=disk_image,
        ssh_key=ssh_key,
        ssh_port=ssh_port,
        console_log=console_log,
        boot_timeout=boot_timeout,
        guest_extra_append=guest_extra_append,
    )
    if not boot["ok"]:
        summary = {
            "ready": False,
            "failure_class": "environment/setup failure",
            "host_checks": host_checks,
            "guest_checks": [{
                "ok": False,
                "name": "boot",
                "error": boot.get("error", "guest failed to boot"),
                "failure_class": boot.get("ssh_ready", {}).get("failure_class"),
                "boot_classification": boot.get("ssh_ready", {}).get("boot_classification"),
            }],
            "environment": {
                "qemu_cmd": boot.get("qemu_cmd", []),
                "boot_failure_class": boot.get("ssh_ready", {}).get("failure_class"),
                "boot_classification": boot.get("ssh_ready", {}).get("boot_classification"),
                "boot_timeline": boot.get("ssh_ready", {}).get("timeline", []),
                "console_excerpt": boot.get("ssh_ready", {}).get("console_excerpt", []),
                "kernel_path": str(kernel),
                "disk_image_path": str(disk_image),
                "append_line": next((boot.get("qemu_cmd", [])[idx + 1] for idx, item in enumerate(boot.get("qemu_cmd", [])) if item == "-append"), ""),
            },
        }
        _write_json(out_dir / "qemu-command.json", {"qemu_cmd": boot.get("qemu_cmd", [])})
        _write_json(out_dir / "ssh-readiness-timeline.json", {"timeline": boot.get("ssh_ready", {}).get("timeline", [])})
        _write_json(out_dir / "preflight_summary.json", summary)
        return summary

    guest_checks: list[dict[str, Any]] = []
    env: dict[str, Any] = {
        "qemu_cmd": boot.get("qemu_cmd", []),
        "boot_timeline": boot.get("ssh_ready", {}).get("timeline", []),
        "boot_banner": boot.get("ssh_ready", {}).get("banner"),
        "guest_extra_append": guest_extra_append,
        "kernel_path": str(kernel),
        "disk_image_path": str(disk_image),
        "append_line": next((boot.get("qemu_cmd", [])[idx + 1] for idx, item in enumerate(boot.get("qemu_cmd", [])) if item == "-append"), ""),
    }
    _update_preflight_progress(out_dir, host_checks=host_checks, guest_checks=guest_checks, environment=env, stage="booted")
    proc = boot["process"]
    try:
        env_prep = _prepare_guest_runtime_environment(ssh_port, ssh_key)
        guest_checks.append({
            "ok": env_prep["ok"],
            "name": "guest_runtime_prep",
            "error": None if env_prep["ok"] else env_prep.get("error", "failed to prepare guest runtime environment"),
        })
        _update_preflight_progress(out_dir, host_checks=host_checks, guest_checks=guest_checks, environment=env, stage="guest-runtime-prep")

        uname = _guest_cmd_retry(ssh_port, ssh_key, "uname -a && uname -m", timeout_sec=15)
        if uname["ok"]:
            lines = [line.strip() for line in uname["stdout"].splitlines() if line.strip()]
            env["uname"] = lines[0] if lines else ""
            env["arch"] = lines[-1] if lines else ""
            guest_checks.append({"ok": env["arch"] == "aarch64", "name": "guest_arch", "value": env["arch"], "error": None if env["arch"] == "aarch64" else f"guest arch must be aarch64, got {env['arch']}"})
        else:
            guest_checks.append({"ok": False, "name": "guest_arch", "error": uname.get("error", "uname failed")})
        _update_preflight_progress(out_dir, host_checks=host_checks, guest_checks=guest_checks, environment=env, stage="guest-arch")

        ssh_probe = _guest_cmd_retry(ssh_port, ssh_key, "true", timeout_sec=DEFAULT_SSH_PROBE_TIMEOUT)
        guest_checks.append({
            "ok": ssh_probe["ok"],
            "name": "ssh_non_interactive",
            "attempts": ssh_probe.get("attempts", []),
            "error": None if ssh_probe["ok"] else ssh_probe.get("error", "ssh command failed"),
        })
        _update_preflight_progress(out_dir, host_checks=host_checks, guest_checks=guest_checks, environment=env, stage="ssh-non-interactive")

        cmdline = _guest_cmd_retry(ssh_port, ssh_key, "cat /proc/cmdline", timeout_sec=15)
        env["cmdline"] = cmdline.get("stdout", "").strip()
        append_line = env.get("append_line", "")
        console_ok = False
        console_source = "guest_cmdline"
        console_value = env["cmdline"]
        console_error = "guest cmdline must include console=ttyAMA0 for serial log capture"
        if cmdline["ok"] and "console=ttyAMA0" in cmdline.get("stdout", ""):
            console_ok = True
        elif "console=ttyAMA0" in append_line:
            console_ok = True
            console_source = "qemu_append"
            console_value = append_line
            console_error = None
        guest_checks.append({
            "ok": console_ok,
            "name": "serial_console",
            "value": console_value,
            "source": console_source,
            "attempts": cmdline.get("attempts", []),
            "error": console_error,
        })
        _update_preflight_progress(out_dir, host_checks=host_checks, guest_checks=guest_checks, environment=env, stage="cmdline")

        debugfs_dir = _guest_cmd_retry(ssh_port, ssh_key, "mkdir -p /sys/kernel/debug && test -d /sys/kernel/debug", timeout_sec=15)
        debugfs_mount = _guest_cmd_retry(ssh_port, ssh_key, "mountpoint -q /sys/kernel/debug || mount -t debugfs debugfs /sys/kernel/debug", timeout_sec=20)
        guest_checks.append({
            "ok": debugfs_dir["ok"] or debugfs_mount["ok"],
            "name": "debugfs_path",
            "attempts": debugfs_dir.get("attempts", []),
            "error": None if debugfs_dir["ok"] or debugfs_mount["ok"] else "/sys/kernel/debug is missing in the guest",
            "source": "path-check" if debugfs_dir["ok"] else "mounted-debugfs" if debugfs_mount["ok"] else "path-check",
        })
        guest_checks.append({
            "ok": debugfs_mount["ok"],
            "name": "debugfs_mounted",
            "attempts": debugfs_mount.get("attempts", []),
            "error": None if debugfs_mount["ok"] else "failed to mount debugfs; ensure CONFIG_DEBUG_FS=y and guest root can mount debugfs",
        })
        _update_preflight_progress(out_dir, host_checks=host_checks, guest_checks=guest_checks, environment=env, stage="debugfs")

        network = _guest_cmd(
            ssh_port,
            ssh_key,
            "if command -v ip >/dev/null 2>&1; then ip route show default | grep -q .; else grep -q '^00000000' /proc/net/route; fi",
            timeout_sec=10,
        )
        guest_checks.append({"ok": network["ok"], "name": "guest_networking", "error": None if network["ok"] else "guest networking is not up; expected a default route for SSH/QEMU user networking"})
        _update_preflight_progress(out_dir, host_checks=host_checks, guest_checks=guest_checks, environment=env, stage="network")

        config_result = _probe_guest_kernel_config(
            ssh_port,
            ssh_key,
            REQUIRED_KERNEL_CONFIGS,
            REQUIRED_KERNEL_CONFIG_ALTERNATIVES,
        )
        config_text = ""
        if config_result["ok"]:
            config_text = config_result["config_text"]
            env["kernel_config_path"] = config_result.get("config_path")
            present, missing = _parse_config_requirements(
                config_text,
                REQUIRED_KERNEL_CONFIGS,
                REQUIRED_KERNEL_CONFIG_ALTERNATIVES,
            )
            env["kernel_config_present"] = present
            env["kernel_config_missing"] = missing
            guest_checks.append({
                "ok": not missing,
                "name": "kernel_config",
                "present": present,
                "missing": missing,
                "error": None if not missing else f"guest kernel config is missing required options: {', '.join(missing)}",
            })
        else:
            guest_checks.append({"ok": False, "name": "kernel_config", "error": config_result["error"]})
        _update_preflight_progress(out_dir, host_checks=host_checks, guest_checks=guest_checks, environment=env, stage="kernel-config")

        guest_checks.extend(_check_guest_net_features(ssh_port, ssh_key, config_text))
        _update_preflight_progress(out_dir, host_checks=host_checks, guest_checks=guest_checks, environment=env, stage="net-modules")

        nf_cap = _guest_cmd_retry(
            ssh_port,
            ssh_key,
            "python3 -c 'import socket; s = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, 12); s.close(); print(\"ok\")'",
            timeout_sec=20,
        )
        guest_checks.append({
            "ok": nf_cap["ok"],
            "name": "nf_tables_exposed",
            "attempts": nf_cap.get("attempts", []),
            "error": None if nf_cap["ok"] else "NETLINK_NETFILTER is not exposed in the guest",
        })
        _update_preflight_progress(out_dir, host_checks=host_checks, guest_checks=guest_checks, environment=env, stage="nf-tables")

        execprog_stage = {"ok": True, "path": guest_syz_execprog_path, "source": "guest-resident"}
        if syz_execprog is not None:
            reuse = _guest_binary_reusable(
                host_path=syz_execprog,
                remote_path=guest_syz_execprog_path,
                ssh_port=ssh_port,
                ssh_key=ssh_key,
                label="guest_syz_execprog_arch",
            )
            if reuse["ok"]:
                execprog_stage = {
                    "ok": True,
                    "path": guest_syz_execprog_path,
                    "source": "guest-reused",
                    "reuse_reason": reuse["reason"],
                }
            else:
                execprog_stage = _copy_to_guest(syz_execprog, guest_syz_execprog_path, ssh_port, ssh_key)
                execprog_stage["path"] = guest_syz_execprog_path
                execprog_stage["source"] = "host-staged"
        guest_checks.append({
            "ok": execprog_stage["ok"],
            "name": "guest_syz_execprog_staged",
            "path": guest_syz_execprog_path,
            "source": execprog_stage["source"],
            "method": execprog_stage.get("method"),
            "stdout": execprog_stage.get("stdout", ""),
            "stderr": execprog_stage.get("stderr", ""),
            "fallback_from": execprog_stage.get("fallback_from"),
            "scp_error": execprog_stage.get("scp_error"),
            "error": None if execprog_stage["ok"] else execprog_stage.get("error", f"failed to stage {guest_syz_execprog_path}"),
        })

        executor_stage = {"ok": True, "path": guest_syz_executor_path, "source": "guest-resident"}
        if syz_executor is not None:
            reuse = _guest_binary_reusable(
                host_path=syz_executor,
                remote_path=guest_syz_executor_path,
                ssh_port=ssh_port,
                ssh_key=ssh_key,
                label="guest_syz_executor_arch",
            )
            if reuse["ok"]:
                executor_stage = {
                    "ok": True,
                    "path": guest_syz_executor_path,
                    "source": "guest-reused",
                    "reuse_reason": reuse["reason"],
                }
            else:
                executor_stage = _copy_to_guest(syz_executor, guest_syz_executor_path, ssh_port, ssh_key)
                executor_stage["path"] = guest_syz_executor_path
                executor_stage["source"] = "host-staged"
        guest_checks.append({
            "ok": executor_stage["ok"],
            "name": "guest_syz_executor_staged",
            "path": guest_syz_executor_path,
            "source": executor_stage["source"],
            "method": executor_stage.get("method"),
            "stdout": executor_stage.get("stdout", ""),
            "stderr": executor_stage.get("stderr", ""),
            "fallback_from": executor_stage.get("fallback_from"),
            "scp_error": executor_stage.get("scp_error"),
            "error": None if executor_stage["ok"] else executor_stage.get("error", f"failed to stage {guest_syz_executor_path}"),
        })
        _update_preflight_progress(out_dir, host_checks=host_checks, guest_checks=guest_checks, environment=env, stage="tool-staging")

        tool_manifest = {
            "guest_syz_execprog": {
                "path": guest_syz_execprog_path,
                "source": execprog_stage.get("source"),
                "method": execprog_stage.get("method"),
                "ok": execprog_stage["ok"],
            },
            "guest_syz_executor": {
                "path": guest_syz_executor_path,
                "source": executor_stage.get("source"),
                "method": executor_stage.get("method"),
                "ok": executor_stage["ok"],
            },
        }
        _write_json(out_dir / "guest_tool_manifest.json", tool_manifest)

        _guest_cmd_retry(ssh_port, ssh_key, f"chmod +x {shlex.quote(guest_syz_execprog_path)} {shlex.quote(guest_syz_executor_path)}", timeout_sec=15)
        guest_checks.append(_check_guest_arm64_binary(ssh_port, ssh_key, guest_syz_execprog_path, "guest_syz_execprog_arch"))
        guest_checks.append(_check_guest_arm64_binary(ssh_port, ssh_key, guest_syz_executor_path, "guest_syz_executor_arch"))
        _update_preflight_progress(out_dir, host_checks=host_checks, guest_checks=guest_checks, environment=env, stage="tool-arch")

        coverfile_check = _check_guest_execprog_coverfile_support(ssh_port, ssh_key, guest_syz_execprog_path)
        env["syz_execprog_help_excerpt"] = coverfile_check.get("excerpt", "")
        guest_checks.append({
            "ok": coverfile_check["ok"],
            "name": "syz_execprog_coverfile",
            "error": coverfile_check["error"],
        })
        _update_preflight_progress(out_dir, host_checks=host_checks, guest_checks=guest_checks, environment=env, stage="coverfile")
    finally:
        if proc is not None:
            shutdown_vm(proc, ssh_port=ssh_port, ssh_key=ssh_key)

    ready = all(check["ok"] for check in host_checks + guest_checks)
    summary = {
        "ready": ready,
        "failure_class": None if ready else "environment/setup failure",
        "host_checks": host_checks,
        "guest_checks": guest_checks,
        "environment": env,
    }
    _write_json(out_dir / "qemu-command.json", {"qemu_cmd": boot.get("qemu_cmd", [])})
    _write_json(out_dir / "ssh-readiness-timeline.json", {"timeline": boot.get("ssh_ready", {}).get("timeline", [])})
    _write_json(out_dir / "preflight_summary.json", summary)
    return summary


def _prepare_guest_execution(
    *,
    syz_execprog: pathlib.Path | None,
    syz_executor: pathlib.Path | None,
    seed: pathlib.Path,
    ssh_port: int,
    ssh_key: pathlib.Path,
    guest_syz_execprog_path: str,
    guest_syz_executor_path: str,
) -> dict[str, Any]:
    runtime_paths = _runtime_paths(GUEST_RUNTIME_DIR)
    runtime_prep = _prepare_guest_runtime_environment(ssh_port, ssh_key)
    copies = {
        "syz_execprog": {"ok": True, "source": "guest-resident", "path": guest_syz_execprog_path},
        "syz_executor": {"ok": True, "source": "guest-resident", "path": guest_syz_executor_path},
        "seed": {"ok": False, "error": "guest runtime preparation failed", "path": runtime_paths["seed_path"]},
    }
    if not runtime_prep["ok"]:
        return {
            "runtime_prep": runtime_prep,
            "copies": copies,
            "chmod": {"ok": False, "error": "skipped after runtime prep failure"},
            "runtime_paths": runtime_paths,
            "ok": False,
        }

    copies["seed"] = _copy_to_guest(seed, runtime_paths["seed_path"], ssh_port, ssh_key)
    copies["seed"]["path"] = runtime_paths["seed_path"]
    if not copies["seed"]["ok"] and _should_retry_runtime_dir(copies["seed"]):
        runtime_paths = _runtime_paths(FALLBACK_GUEST_RUNTIME_DIR)
        fallback_seed = _copy_to_guest(seed, runtime_paths["seed_path"], ssh_port, ssh_key)
        fallback_seed["path"] = runtime_paths["seed_path"]
        fallback_seed["fallback_runtime_dir"] = FALLBACK_GUEST_RUNTIME_DIR
        fallback_seed["initial_failure"] = {
            "error": copies["seed"].get("error"),
            "stderr": copies["seed"].get("stderr"),
            "scp_error": copies["seed"].get("scp_error"),
            "scp_stderr": copies["seed"].get("scp_stderr"),
        }
        copies["seed"] = fallback_seed
    if syz_execprog is not None:
        reuse = _guest_binary_reusable(
            host_path=syz_execprog,
            remote_path=guest_syz_execprog_path,
            ssh_port=ssh_port,
            ssh_key=ssh_key,
            label="guest_syz_execprog_arch",
        )
        if reuse["ok"]:
            copies["syz_execprog"] = {
                "ok": True,
                "source": "guest-reused",
                "path": guest_syz_execprog_path,
                "reuse_reason": reuse["reason"],
            }
        else:
            copies["syz_execprog"] = _copy_to_guest(syz_execprog, guest_syz_execprog_path, ssh_port, ssh_key)
            copies["syz_execprog"]["source"] = "host-staged"
            copies["syz_execprog"]["path"] = guest_syz_execprog_path
    if syz_executor is not None:
        reuse = _guest_binary_reusable(
            host_path=syz_executor,
            remote_path=guest_syz_executor_path,
            ssh_port=ssh_port,
            ssh_key=ssh_key,
            label="guest_syz_executor_arch",
        )
        if reuse["ok"]:
            copies["syz_executor"] = {
                "ok": True,
                "source": "guest-reused",
                "path": guest_syz_executor_path,
                "reuse_reason": reuse["reason"],
            }
        else:
            copies["syz_executor"] = _copy_to_guest(syz_executor, guest_syz_executor_path, ssh_port, ssh_key)
            copies["syz_executor"]["source"] = "host-staged"
            copies["syz_executor"]["path"] = guest_syz_executor_path
    chmod = _guest_cmd(
        ssh_port,
        ssh_key,
        f"mkdir -p {shlex.quote(GUEST_RUNTIME_DIR)} {shlex.quote(FALLBACK_GUEST_RUNTIME_DIR)} && chmod +x {shlex.quote(guest_syz_execprog_path)} {shlex.quote(guest_syz_executor_path)} && dmesg -c >/dev/null 2>&1 || true",
        timeout_sec=20,
    )
    return {
        "runtime_prep": runtime_prep,
        "copies": copies,
        "chmod": chmod,
        "runtime_paths": runtime_paths,
        "ok": runtime_prep["ok"] and all(item["ok"] for item in copies.values()) and chmod["ok"],
    }


def _run_guest_seed(
    *,
    syz_execprog: pathlib.Path | None,
    syz_executor: pathlib.Path | None,
    seed: pathlib.Path,
    ssh_port: int,
    ssh_key: pathlib.Path,
    timeout_sec: int,
    threaded: bool,
    procs: int,
    seed_out: pathlib.Path,
    guest_syz_execprog_path: str,
    guest_syz_executor_path: str,
) -> dict[str, Any]:
    prep = _prepare_guest_execution(
        syz_execprog=syz_execprog,
        syz_executor=syz_executor,
        seed=seed,
        ssh_port=ssh_port,
        ssh_key=ssh_key,
        guest_syz_execprog_path=guest_syz_execprog_path,
        guest_syz_executor_path=guest_syz_executor_path,
    )
    _write_json(seed_out / "copy_summary.json", prep)
    if not prep["ok"]:
        return {
            "ok": False,
            "timed_out": False,
            "returncode": None,
            "stdout": "",
            "stderr": "guest preparation failed",
            "duration_sec": 0.0,
            "error": "failed to copy seed or syzkaller binaries into guest",
            "cmd": [],
            "coverage_copied": False,
        }

    runtime_paths = prep.get("runtime_paths", _runtime_paths(GUEST_RUNTIME_DIR))
    remote_cover = runtime_paths["cover_path"]
    cmd = (
        f"{shlex.quote(guest_syz_execprog_path)} -executor={shlex.quote(guest_syz_executor_path)} -repeat=0 -procs={procs} "
        f"-threaded={1 if threaded else 0} -coverfile={remote_cover} {shlex.quote(runtime_paths['seed_path'])}"
    )
    result = _guest_cmd(ssh_port, ssh_key, cmd, timeout_sec=timeout_sec)
    coverage_pull = _fetch_from_guest(remote_cover, seed_out / "kcov.cover", ssh_port, ssh_key)
    result["coverage_copied"] = coverage_pull["ok"]
    result["coverage_pull"] = coverage_pull
    result["cmd"] = cmd
    return result


def _collect_guest_dmesg(ssh_port: int, ssh_key: pathlib.Path) -> dict[str, Any]:
    return _guest_cmd(ssh_port, ssh_key, "dmesg", timeout_sec=20)


def _candidate_match_from_crash(crash: dict[str, Any] | None, target_profile: dict[str, Any]) -> dict[str, Any]:
    if crash is None:
        return {
            "focus_frame_hit": False,
            "focus_file_hit": False,
            "free_use_hint_match": False,
            "uaf_type_match": False,
            "match_score": 0.0,
            "crash_frames": [],
            "crash_files": [],
            "net_enrichment": {
                "is_net_crash": False,
                "subsystem_relevance_score": 0.0,
                "lifecycle_frame_hits": [],
                "source_file_hits": [],
                "teardown_frame_hits": [],
                "use_frame_hits": [],
                "has_teardown_use_pair": False,
            },
        }
    parsed = parse_kasan_report(crash["raw_excerpt"])
    if parsed is None:
        parsed = {
            "type": crash.get("bug_type", "unknown"),
            "trigger_function": crash.get("trigger_function", "unknown"),
            "allocator": crash.get("allocator"),
            "stack_frames": crash.get("stack_frames", []),
            "source_files": crash.get("source_files", []),
        }
    base_match = match_crash(parsed, target_profile)
    enriched = enrich_crash_match(parsed, base_match)
    enriched["crash_frames"] = parsed.get("stack_frames", [])
    enriched["crash_files"] = parsed.get("source_files", [])
    return enriched


def _summarize_execution(items: list[dict[str, Any]]) -> dict[str, Any]:
    phase_order = {"unknown": 0, "bootstrap": 1, "configure": 2, "trigger": 3}
    best = max(items, key=lambda item: phase_order.get(item["execution_evidence"]["phase_reached"], 0), default=None)
    phases = sorted({phase for item in items for phase in item["execution_evidence"]["phases_exercised"]})
    return {
        "seed_count": len(items),
        "target_family_hit": any(item["execution_evidence"]["target_family_hit"] for item in items),
        "phase_reached": best["execution_evidence"]["phase_reached"] if best else "unknown",
        "phases_exercised": phases,
        "prefix_preserved": any(item["execution_evidence"]["prefix_preserved"] for item in items),
        "trigger_phase_reached": any(item["execution_evidence"]["trigger_phase_reached"] for item in items),
        "prefix_valid_rate": round(sum(1 for item in items if item["execution_evidence"]["prefix_preserved"]) / len(items), 3) if items else 0.0,
    }


def _summarize_crashes(items: list[dict[str, Any]]) -> dict[str, Any]:
    crash_items = [item for item in items if item["crash_evidence"]["crash_detected"]]
    primary = max(crash_items, key=lambda item: item["candidate_evidence"]["match_score"], default=None)
    signatures: dict[str, int] = {}
    for item in crash_items:
        signature = item["crash_evidence"].get("signature") or "no-signature"
        signatures[signature] = signatures.get(signature, 0) + 1
    return {
        "crash_detected": bool(crash_items),
        "crash_count": len(crash_items),
        "real_crash_count": sum(1 for item in crash_items if item["crash_evidence"]["real_crash_signal"]),
        "real_crash_signal": bool(primary and primary["crash_evidence"].get("real_crash_signal")),
        "crash_kind": primary["crash_evidence"]["crash_kind"] if primary else "none",
        "title": primary["crash_evidence"].get("title") if primary else None,
        "signature": primary["crash_evidence"].get("signature") if primary else None,
        "top_frames": primary["crash_evidence"].get("top_frames", []) if primary else [],
        "source_files": primary["crash_evidence"].get("source_files", []) if primary else [],
        "signatures": signatures,
        "primary_seed": primary["seed"] if primary else None,
    }


def _summarize_candidate(items: list[dict[str, Any]]) -> dict[str, Any]:
    best = max(items, key=lambda item: item["candidate_evidence"]["match_score"], default=None)
    return {
        "path_relevant": any(item["candidate_evidence"]["path_relevant"] for item in items),
        "match_score": best["candidate_evidence"]["match_score"] if best else 0.0,
        "specific_candidate_alignment": any(item["candidate_evidence"]["specific_candidate_alignment"] for item in items),
        "alignment_quality": best["candidate_evidence"]["alignment_quality"] if best else "unrelated",
        "subsystem_relevance_score": max((item["candidate_evidence"]["subsystem_relevance_score"] for item in items), default=0.0),
        "specific_free_hit": any(item["candidate_evidence"]["specific_free_hit"] for item in items),
        "specific_use_hit": any(item["candidate_evidence"]["specific_use_hit"] for item in items),
    }


def generate_manual_novelty_report(
    *,
    crash_evidence_summary: dict[str, Any],
    candidate_evidence_summary: dict[str, Any],
    reproducibility_summary: dict[str, Any],
    seen_signatures: dict[str, int],
) -> dict[str, Any]:
    signature = crash_evidence_summary.get("signature")
    duplicate_indicators: list[str] = []
    if signature and seen_signatures.get(signature, 0) > 1:
        duplicate_indicators.append("same signature observed multiple times within this live campaign")
    if crash_evidence_summary.get("title"):
        duplicate_indicators.append(f"search syzbot/netfilter using crash title: {crash_evidence_summary['title']}")
    return {
        "status": "unchecked",
        "crash_title": crash_evidence_summary.get("title"),
        "crash_signature": signature,
        "top_frames": crash_evidence_summary.get("top_frames", []),
        "likely_subsystem": "netfilter/nf_tables" if candidate_evidence_summary.get("path_relevant") else "unknown",
        "candidate_alignment_summary": {
            "match_score": candidate_evidence_summary.get("match_score"),
            "specific_candidate_alignment": candidate_evidence_summary.get("specific_candidate_alignment"),
            "alignment_quality": candidate_evidence_summary.get("alignment_quality"),
        },
        "reproducibility": reproducibility_summary,
        "likely_duplicate_indicators": duplicate_indicators,
        "checklist": [
            "compare against syzbot netfilter reports",
            "compare against known fixed bugs",
            "compare against current tree/patch state",
            "do not call this new until checked",
        ],
    }


def _seed_environment_snapshot(preflight: dict[str, Any]) -> dict[str, Any]:
    return {
        "ready": preflight.get("ready", False),
        "environment": preflight.get("environment", {}),
        "host_checks": preflight.get("host_checks", []),
        "guest_checks": preflight.get("guest_checks", []),
    }


def _classify_seed_result(
    *,
    execution_evidence: dict[str, Any],
    crash_evidence: dict[str, Any],
    exec_result: dict[str, Any] | None = None,
    boot_error: str | None = None,
) -> dict[str, Any]:
    exec_result = exec_result or {}
    stdout = exec_result.get("stdout", "") or ""
    stderr = exec_result.get("stderr", "") or ""
    progress_signals = {
        "stdout_nonempty": bool(stdout.strip()),
        "stderr_nonempty": bool(stderr.strip()),
        "coverage_copied": bool(exec_result.get("coverage_copied")),
        "duration_sec": exec_result.get("duration_sec"),
        "timed_out": bool(exec_result.get("timed_out")),
        "returncode": exec_result.get("returncode"),
        "error": exec_result.get("error"),
    }
    if boot_error:
        classification = "setup-failure"
        reasons = ["Guest boot or SSH readiness failed before seed execution began."]
    elif exec_result.get("timed_out"):
        had_progress = any([progress_signals["stdout_nonempty"], progress_signals["stderr_nonempty"], progress_signals["coverage_copied"]])
        if had_progress:
            classification = "timed-out"
            reasons = ["Guest seed execution exceeded the per-seed timeout after producing some progress."]
        else:
            classification = "stalled"
            reasons = ["Guest seed execution exceeded the per-seed timeout without observable progress."]
    elif exec_result and not exec_result.get("ok", False):
        classification = "guest-exec-failure"
        reasons = ["Guest command failed before a classified runtime result could be observed."]
    elif crash_evidence.get("crash_detected"):
        classification = "completed-crash"
        reasons = ["Seed execution completed and the guest emitted a kernel crash signal."]
    elif not execution_evidence.get("target_family_hit") or execution_evidence.get("phase_reached") == "unknown":
        classification = "target-not-reached"
        reasons = ["Seed completed but did not meaningfully reach the NETLINK_NETFILTER target path."]
    else:
        classification = "completed-no-crash"
        reasons = ["Seed execution completed without a classified kernel crash."]

    ssh_timeout = bool(exec_result.get("timed_out") and exec_result.get("error") and "timeout" in str(exec_result.get("error", "")).lower())
    progress_signals["ssh_command_timeout"] = ssh_timeout
    progress_signals["classification_basis"] = "boot" if boot_error else "exec"
    return {
        "classification": classification,
        "reasons": reasons,
        "progress_signals": progress_signals,
    }


def _run_one_live_seed(
    *,
    seed: pathlib.Path,
    state_model: dict[str, Any],
    target_profile: dict[str, Any],
    manifest: dict[str, Any],
    kernel: pathlib.Path,
    disk_image: pathlib.Path,
    ssh_key: pathlib.Path,
    ssh_port: int,
    syz_execprog: pathlib.Path | None,
    syz_executor: pathlib.Path | None,
    timeout_sec: int,
    threaded: bool,
    procs: int,
    seed_out: pathlib.Path,
    preflight: dict[str, Any],
    boot_timeout: int,
    guest_syz_execprog_path: str,
    guest_syz_executor_path: str,
    guest_extra_append: str,
    progress_out_dir: pathlib.Path | None = None,
    progress_stage_index: int | None = None,
    progress_stage_total: int | None = None,
    progress_stage_name: str | None = None,
    progress_seed_index: int | None = None,
    progress_seed_total: int | None = None,
) -> dict[str, Any]:
    seed_out.mkdir(parents=True, exist_ok=True)
    (seed_out / seed.name).write_text(seed.read_text(encoding="utf-8"), encoding="utf-8")
    _write_json(seed_out / "environment_preflight_summary.json", _seed_environment_snapshot(preflight))
    progress_started = time.monotonic()

    def update_seed_progress(substage: str, status: str, *, detail: str | None = None) -> None:
        if progress_out_dir is None or progress_stage_index is None or progress_stage_total is None or progress_stage_name is None:
            return
        _write_progress(
            progress_out_dir,
            stage_index=progress_stage_index,
            stage_total=progress_stage_total,
            stage_name=progress_stage_name,
            substage=substage,
            status=status,
            seed=seed.name,
            current=progress_seed_index,
            total=progress_seed_total,
            elapsed_sec=time.monotonic() - progress_started,
            timeout_sec=timeout_sec,
            detail=detail,
        )

    calls = _canonical_seed_calls(seed, manifest)
    prefix_valid = _score_prefix(calls, state_model) == 1.0
    chain_intact = _score_resource_chain(calls, state_model) >= 0.9
    phase_progress = _score_phase_progress(calls, state_model)
    phase_reached = _phase_name(phase_progress)

    console_log = seed_out / "console.log"
    boot = _boot_guest(
        kernel=kernel,
        disk_image=disk_image,
        ssh_key=ssh_key,
        ssh_port=ssh_port,
        console_log=console_log,
        boot_timeout=boot_timeout,
        guest_extra_append=guest_extra_append,
    )
    update_seed_progress("boot", "running", detail="guest boot started")
    if not boot["ok"]:
        execution_evidence = build_execution_evidence(
            seed=seed.name,
            calls=calls,
            phase_reached="unknown",
            phase_progress=0.0,
            prefix_valid=prefix_valid,
            resource_chain_intact=chain_intact,
            trigger_phase_reached=False,
        )
        crash_evidence = build_crash_evidence(crash=None, exec_result={"timed_out": False})
        candidate_evidence = build_candidate_evidence(
            candidate_match=_candidate_match_from_crash(None, target_profile),
            target_profile=target_profile,
        )
        seed_execution_status = _classify_seed_result(
            execution_evidence=execution_evidence,
            crash_evidence=crash_evidence,
            boot_error=boot.get("error"),
        )
        result = {
            "seed": seed.name,
            "boot_failed": True,
            "boot_error": boot.get("error"),
            "execution_evidence": execution_evidence,
            "crash_evidence": crash_evidence,
            "candidate_evidence": candidate_evidence,
            "triage_verdict": "insufficient_data",
            "subsystem_relevance": "unrelated",
            "seed_execution_status": seed_execution_status,
            "seed_dir": str(seed_out),
        }
        _write_json(seed_out / "seed_execution_status.json", seed_execution_status)
        _write_json(seed_out / "seed_run_summary.json", result)
        update_seed_progress("boot", "failed", detail=boot.get("error"))
        return result

    proc = boot["process"]
    try:
        update_seed_progress("exec", "running", detail="executing syz-execprog in guest")
        exec_result = _run_guest_seed(
            syz_execprog=syz_execprog,
            syz_executor=syz_executor,
            seed=seed,
            ssh_port=ssh_port,
            ssh_key=ssh_key,
            timeout_sec=timeout_sec,
            threaded=threaded,
            procs=procs,
            seed_out=seed_out,
            guest_syz_execprog_path=guest_syz_execprog_path,
            guest_syz_executor_path=guest_syz_executor_path,
        )
        update_seed_progress("dmesg", "running", detail="collecting guest dmesg")
        dmesg_result = _collect_guest_dmesg(ssh_port, ssh_key)
    finally:
        shutdown_vm(proc, ssh_port=ssh_port, ssh_key=ssh_key)

    _write_text(seed_out / "syz-execprog.stdout.txt", exec_result.get("stdout", ""))
    _write_text(seed_out / "syz-execprog.stderr.txt", exec_result.get("stderr", ""))
    _write_text(seed_out / "guest.dmesg.txt", dmesg_result.get("stdout", ""))

    crash_text = dmesg_result.get("stdout", "")
    crash = parse_kernel_crash(crash_text)
    candidate_match = _candidate_match_from_crash(crash, target_profile)
    candidate_evidence = build_candidate_evidence(candidate_match=candidate_match, target_profile=target_profile)
    subsystem_relevance = classify_crash_subsystem_relevance(
        {
            "stack_frames": candidate_match.get("crash_frames", []),
            "source_files": candidate_match.get("crash_files", []),
        }
    )
    execution_evidence = build_execution_evidence(
        seed=seed.name,
        calls=calls,
        phase_reached=phase_reached,
        phase_progress=phase_progress,
        prefix_valid=prefix_valid,
        resource_chain_intact=chain_intact,
        trigger_phase_reached=phase_reached == "trigger",
    )
    crash_evidence = build_crash_evidence(crash=crash, exec_result=exec_result)
    triage = build_triage_report(crash_text, target_profile, state_model, calls)

    _write_json(seed_out / "execution_evidence.json", execution_evidence)
    _write_json(seed_out / "crash_evidence.json", crash_evidence)
    _write_json(seed_out / "candidate_alignment_report.json", candidate_evidence)
    _write_json(seed_out / "triage_report_v1.json", triage)

    seed_verdict = classify_net_runtime_verdict(
        preflight_ready=preflight.get("ready", False),
        execution_evidence_summary=execution_evidence,
        crash_evidence_summary=crash_evidence,
        candidate_evidence_summary=candidate_evidence,
        reproducibility_summary=classify_reproducibility(attempts=0, crash_count=0),
    )
    seed_execution_status = _classify_seed_result(
        execution_evidence=execution_evidence,
        crash_evidence=crash_evidence,
        exec_result=exec_result,
    )
    _write_json(seed_out / "runtime_verdict.json", seed_verdict)
    _write_json(seed_out / "seed_execution_status.json", seed_execution_status)

    summary = {
        "seed": seed.name,
        "seed_dir": str(seed_out),
        "execution_evidence": execution_evidence,
        "crash_evidence": crash_evidence,
        "candidate_evidence": candidate_evidence,
        "triage_verdict": triage["verdict"],
        "subsystem_relevance": subsystem_relevance,
        "seed_execution_status": seed_execution_status,
        "exec_result": {
            "returncode": exec_result.get("returncode"),
            "timed_out": exec_result.get("timed_out"),
            "duration_sec": exec_result.get("duration_sec"),
            "coverage_copied": exec_result.get("coverage_copied", False),
            "error": exec_result.get("error"),
            "cmd": exec_result.get("cmd"),
        },
        "dmesg_error": dmesg_result.get("error"),
    }
    _write_json(seed_out / "seed_run_summary.json", summary)
    update_seed_progress(
        "complete",
        "finished",
        detail=f"classification={seed_execution_status.get('classification')}",
    )
    return summary


def _summarize_seed_results(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    primary = None
    for item in items:
        status = item.get("seed_execution_status", {})
        classification = status.get("classification", "guest-exec-failure")
        counts[classification] = counts.get(classification, 0) + 1
        if primary is None:
            primary = {
                "classification": classification,
                "seed": item.get("seed"),
                "seed_dir": item.get("seed_dir"),
                "reasons": status.get("reasons", []),
                "progress_signals": status.get("progress_signals", {}),
            }
    return {
        "counts": counts,
        "primary": primary or {"classification": "guest-exec-failure", "seed": None, "seed_dir": None, "reasons": ["No seed results were recorded."], "progress_signals": {}},
    }


def _run_repro_attempts(
    *,
    crash_seed: pathlib.Path,
    crash_signature: str | None,
    attempts: int,
    out_dir: pathlib.Path,
    runner_kwargs: dict[str, Any],
) -> dict[str, Any]:
    attempt_summaries: list[dict[str, Any]] = []
    same_signature_crashes = 0
    for attempt in range(1, attempts + 1):
        attempt_dir = out_dir / f"attempt-{attempt}"
        result = _run_one_live_seed(seed=crash_seed, seed_out=attempt_dir, **runner_kwargs)
        crash = result["crash_evidence"]
        same_signature = bool(crash.get("signature") and crash.get("signature") == crash_signature)
        if same_signature:
            same_signature_crashes += 1
        attempt_summary = {
            "attempt": attempt,
            "seed": crash_seed.name,
            "crash_detected": crash.get("crash_detected", False),
            "signature": crash.get("signature"),
            "same_signature": same_signature,
            "verdict": result.get("triage_verdict"),
            "seed_dir": result["seed_dir"],
        }
        attempt_summaries.append(attempt_summary)
        _write_json(attempt_dir / "repro_attempt_summary.json", attempt_summary)
    repro = classify_reproducibility(attempts=attempts, crash_count=same_signature_crashes)
    summary = {
        **repro,
        "seed": crash_seed.name,
        "expected_signature": crash_signature,
        "attempt_summaries": attempt_summaries,
    }
    _write_json(out_dir / "repro_summary.json", summary)
    handoff = {
        "seed": crash_seed.name,
        "expected_signature": crash_signature,
        "repro_command": runner_kwargs.get("repro_command"),
        "notes": [
            "Use the preserved seed under crashes/ or repro/ as the reducer starting point.",
            "Do not claim novelty until the known-bug review template is completed.",
        ],
    }
    _write_json(out_dir / "minimization_handoff.json", handoff)
    return summary


def run_net_runtime_lane(
    *,
    state_model_path: pathlib.Path,
    target_profile_path: pathlib.Path,
    seeds_dir: pathlib.Path,
    out_dir: pathlib.Path,
    syz_execprog: pathlib.Path | None,
    syz_executor: pathlib.Path | None,
    kernel: pathlib.Path,
    disk_image: pathlib.Path,
    ssh_key: pathlib.Path,
    ssh_port: int = 10022,
    timeout_sec: int = 180,
    threaded: bool = True,
    procs: int = 1,
    boot_timeout: int = 180,
    extended_rounds: int = 0,
    stop_after_stage: str | None = None,
    repro_attempts: int = 3,
    known_bug_review_path: pathlib.Path | None = None,
    guest_syz_execprog_path: str = DEFAULT_GUEST_SYZ_EXECPROG,
    guest_syz_executor_path: str = DEFAULT_GUEST_SYZ_EXECUTOR,
    guest_extra_append: str = DEFAULT_GUEST_EXTRA_APPEND,
    proof_mode: str = DEFAULT_PROOF_MODE,
    proof_kernel_meta_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ["preflight", "campaign", "runtime", "crashes", "repro", "logs"]:
        (out_dir / name).mkdir(parents=True, exist_ok=True)
    total_stages = 1 + len(STAGE_SPECS) + (1 if extended_rounds > 0 else 0)
    _write_progress(
        out_dir,
        stage_index=1,
        stage_total=total_stages,
        stage_name="preflight",
        substage="start",
        status="running",
        detail="strict live preflight started",
    )

    state_model = _load_json(state_model_path)
    target_profile = _load_json(target_profile_path)
    if state_model.get("subsystem") != "net":
        raise ValueError(f"net runtime lane requires net state model; got {state_model.get('subsystem')}")

    manifest = resolve_target_manifest(subsystem=state_model.get("subsystem"), target_family=state_model.get("target_family"))
    if proof_mode not in PROOF_MODES:
        raise ValueError(f"unsupported proof mode: {proof_mode}")
    seeds = _ordered_seed_paths(seeds_dir, proof_mode=proof_mode)
    if not seeds:
        raise ValueError(f"no .prog seeds found in {seeds_dir}")
    proof_kernel_meta = _load_json(proof_kernel_meta_path) if proof_kernel_meta_path and proof_kernel_meta_path.exists() else None
    seed_manifest_path = seeds_dir / "seed_manifest.json"
    seed_manifest = _load_json(seed_manifest_path) if seed_manifest_path.exists() else {"seeds": [{"name": path.name} for path in seeds]}
    file_ranking = rank_net_files(
        candidate={"candidate_id": state_model.get("candidate_id")},
        target_profile=target_profile,
        manifest=manifest,
        source_frame_summary={},
    )
    seed_ranking = rank_net_seeds(
        seed_manifest=seed_manifest,
        target_profile=target_profile,
        candidate={"candidate_id": state_model.get("candidate_id")},
        proof_mode=proof_mode,
    )
    _write_json(
        out_dir / "logs" / "ranking_input.json",
        {
            "candidate_id": state_model.get("candidate_id"),
            "proof_mode": proof_mode,
            "focus_files": target_profile.get("focus_files", []),
            "free_use_hints": target_profile.get("free_use_hints", []),
            "seed_manifest": seed_manifest,
        },
    )
    _write_json(
        out_dir / "logs" / "ranking_decision.json",
        {
            "ordered_seeds": [seed.name for seed in seeds],
            "ranked_files": file_ranking.get("ranked_files", []),
            "ranked_seeds": seed_ranking.get("ranked_seeds", []),
        },
    )
    _write_json(
        out_dir / "logs" / "proof_manifest.json",
        _proof_manifest(
            proof_mode=proof_mode,
            kernel=kernel,
            disk_image=disk_image,
            guest_syz_execprog_path=guest_syz_execprog_path,
            guest_syz_executor_path=guest_syz_executor_path,
            seed=seeds[0] if seeds else None,
            timeout_sec=timeout_sec,
            threaded=threaded,
            procs=procs,
            proof_kernel_meta=proof_kernel_meta,
        ),
    )

    preflight = run_live_preflight(
        kernel=kernel,
        disk_image=disk_image,
        ssh_key=ssh_key,
        syz_execprog=syz_execprog,
        syz_executor=syz_executor,
        out_dir=out_dir / "preflight",
        ssh_port=ssh_port,
        boot_timeout=boot_timeout,
        guest_syz_execprog_path=guest_syz_execprog_path,
        guest_syz_executor_path=guest_syz_executor_path,
        guest_extra_append=guest_extra_append,
    )
    if not preflight["ready"]:
        _write_progress(
            out_dir,
            stage_index=1,
            stage_total=total_stages,
            stage_name="preflight",
            substage="summary",
            status="failed",
            detail=preflight.get("failure_class", "environment/setup failure"),
        )
        verdict = classify_net_runtime_verdict(
            preflight_ready=False,
            execution_evidence_summary={"target_family_hit": False, "phase_reached": "unknown", "prefix_preserved": False, "trigger_phase_reached": False},
            crash_evidence_summary={"crash_detected": False, "crash_kind": "none", "real_crash_signal": False},
            candidate_evidence_summary={"path_relevant": False, "match_score": 0.0, "specific_candidate_alignment": False},
            reproducibility_summary=classify_reproducibility(attempts=0, crash_count=0),
        )
        verdict["single_seed_result"] = None
        verdict["executed_stages"] = []
        kernel_provenance = build_kernel_provenance(
            kernel=kernel,
            disk_image=disk_image,
            preflight_environment=preflight.get("environment", {}),
            proof_kernel_meta=proof_kernel_meta,
        )
        environment_summary = {
            "proof_mode": proof_mode,
            "proof_kernel_meta": proof_kernel_meta,
            "kernel": str(kernel),
            "disk_image": str(disk_image),
            "ssh_port": ssh_port,
            "arch": preflight.get("environment", {}).get("arch"),
            "cmdline": preflight.get("environment", {}).get("cmdline"),
            "guest_syz_execprog_path": guest_syz_execprog_path,
            "guest_syz_executor_path": guest_syz_executor_path,
            "guest_extra_append": guest_extra_append,
            "kernel_config_path": preflight.get("environment", {}).get("kernel_config_path"),
            "kernel_config_present": preflight.get("environment", {}).get("kernel_config_present", []),
            "kernel_config_missing": preflight.get("environment", {}).get("kernel_config_missing", []),
        }
        source_frame_summary = build_source_frame_summary(
            crash_evidence_summary={"title": None, "signature": None, "top_frames": [], "source_files": []},
            candidate_evidence_summary={"path_relevant": False, "specific_candidate_alignment": False},
            target_profile=target_profile,
            reproducibility_summary=classify_reproducibility(attempts=0, crash_count=0),
        )
        blocker_report = build_blocker_report(
            runtime_verdict=verdict,
            single_seed_result=None,
            preflight_summary_path=out_dir / "preflight" / "preflight_summary.json",
            seed_dir=None,
        )
        lab_state = classify_lab_net_state(
            runtime_verdict=verdict,
            source_frame_summary=source_frame_summary,
            reproducibility_summary=classify_reproducibility(attempts=0, crash_count=0),
            lab_context={"lab_only": proof_mode == "controlled"},
        )
        _write_json(out_dir / "runtime" / "kernel_provenance.json", kernel_provenance)
        _write_json(out_dir / "runtime" / "guest_environment_summary.json", environment_summary)
        _write_json(out_dir / "runtime" / "source_frame_summary.json", source_frame_summary)
        if blocker_report is not None:
            _write_json(out_dir / "runtime" / "blocker_report.json", blocker_report)
        _write_json(out_dir / "runtime" / "lab_state.json", lab_state)
        _write_json(
            out_dir / "runtime" / "lab_run_bundle.json",
            build_lab_run_bundle(
                kernel_provenance=kernel_provenance,
                source_frame_summary=source_frame_summary,
                runtime_verdict=verdict,
                lab_state=lab_state,
                blocker_report=blocker_report,
                guest_environment_summary=environment_summary,
                single_seed_result=None,
                seed_dir=None,
                out_dir=out_dir,
            ),
        )
        _write_json(out_dir / "runtime" / "final_verdict.json", verdict)
        return {"preflight": preflight, "runtime_verdict": verdict}
    _write_progress(
        out_dir,
        stage_index=1,
        stage_total=total_stages,
        stage_name="preflight",
        substage="summary",
        status="finished",
        detail="strict live preflight passed",
    )

    stage_specs = list(STAGE_SPECS)
    if extended_rounds > 0:
        stage_specs.append(("extended-fuzzing", len(seeds) * extended_rounds))
    if stop_after_stage:
        filtered: list[tuple[str, int | None]] = []
        for stage_name, stage_limit in stage_specs:
            filtered.append((stage_name, stage_limit))
            if stage_name == stop_after_stage:
                break
        if not filtered or filtered[-1][0] != stop_after_stage:
            raise ValueError(f"unknown stage name: {stop_after_stage}")
        stage_specs = filtered

    all_items: list[dict[str, Any]] = []
    stage_summaries: list[dict[str, Any]] = []
    seen_signatures: dict[str, int] = {}

    runner_kwargs = {
        "state_model": state_model,
        "target_profile": target_profile,
        "manifest": manifest,
        "kernel": kernel,
        "disk_image": disk_image,
        "ssh_key": ssh_key,
        "ssh_port": ssh_port,
        "syz_execprog": syz_execprog,
        "syz_executor": syz_executor,
        "timeout_sec": timeout_sec,
        "threaded": threaded,
        "procs": procs,
        "preflight": preflight,
        "boot_timeout": boot_timeout,
        "guest_syz_execprog_path": guest_syz_execprog_path,
        "guest_syz_executor_path": guest_syz_executor_path,
        "guest_extra_append": guest_extra_append,
    }

    for stage_offset, (stage_name, stage_limit) in enumerate(stage_specs, start=1):
        stage_index = 1 + stage_offset
        stage_dir = out_dir / "campaign" / f"{stage_index:02d}-{stage_name}"
        stage_dir.mkdir(parents=True, exist_ok=True)
        if stage_name == "extended-fuzzing":
            stage_seeds = (seeds * extended_rounds)[: stage_limit or len(seeds)]
        else:
            stage_seeds = seeds[: stage_limit or len(seeds)]
        _write_progress(
            out_dir,
            stage_index=stage_index,
            stage_total=total_stages,
            stage_name=stage_name,
            substage="start",
            status="running",
            current=0,
            total=len(stage_seeds),
            detail="stage started",
        )
        stage_items: list[dict[str, Any]] = []
        for run_index, seed in enumerate(stage_seeds, start=1):
            seed_dir = out_dir / "runtime" / stage_name / f"{run_index:02d}-{seed.stem}"
            _write_progress(
                out_dir,
                stage_index=stage_index,
                stage_total=total_stages,
                stage_name=stage_name,
                substage="seed-start",
                status="running",
                seed=seed.name,
                current=run_index,
                total=len(stage_seeds),
                timeout_sec=timeout_sec,
                detail="seed execution started",
            )
            item = _run_one_live_seed(
                seed=seed,
                seed_out=seed_dir,
                progress_out_dir=out_dir,
                progress_stage_index=stage_index,
                progress_stage_total=total_stages,
                progress_stage_name=stage_name,
                progress_seed_index=run_index,
                progress_seed_total=len(stage_seeds),
                **runner_kwargs,
            )
            item["stage_name"] = stage_name
            stage_items.append(item)
            all_items.append(item)
            signature = item["crash_evidence"].get("signature")
            if signature:
                seen_signatures[signature] = seen_signatures.get(signature, 0) + 1
            _write_progress(
                out_dir,
                stage_index=stage_index,
                stage_total=total_stages,
                stage_name=stage_name,
                substage="seed-finished",
                status="running",
                seed=seed.name,
                current=run_index,
                total=len(stage_seeds),
                detail=f"classification={item.get('seed_execution_status', {}).get('classification', 'unknown')}",
            )
        stage_summary = {
            "stage_name": stage_name,
            "seed_count": len(stage_items),
            "phase_reached": _summarize_execution(stage_items).get("phase_reached", "unknown"),
            "target_family_hit": any(item["execution_evidence"]["target_family_hit"] for item in stage_items),
            "crash_count": sum(1 for item in stage_items if item["crash_evidence"]["crash_detected"]),
            "seed_result_summary": _summarize_seed_results(stage_items),
            "seed_dirs": [item["seed_dir"] for item in stage_items],
        }
        stage_summaries.append(stage_summary)
        _write_json(stage_dir / "stage_summary.json", stage_summary)
        _write_progress(
            out_dir,
            stage_index=stage_index,
            stage_total=total_stages,
            stage_name=stage_name,
            substage="summary",
            status="finished",
            current=len(stage_seeds),
            total=len(stage_seeds),
            detail=f"crashes={stage_summary['crash_count']}",
        )

    execution_summary = _summarize_execution(all_items)
    crash_summary = _summarize_crashes(all_items)
    candidate_summary = _summarize_candidate(all_items)
    seed_result_summary = _summarize_seed_results(all_items)
    single_seed_stage = next((summary for summary in stage_summaries if summary["stage_name"] == "single-seed-validation"), None)

    repro_summary = classify_reproducibility(attempts=0, crash_count=0)
    if crash_summary.get("signature") and crash_summary.get("primary_seed"):
        crash_seed_path = seeds_dir / crash_summary["primary_seed"]
        _write_progress(
            out_dir,
            stage_index=total_stages,
            stage_total=total_stages,
            stage_name="repro",
            substage="start",
            status="running",
            seed=crash_seed_path.name,
            current=0,
            total=repro_attempts,
            detail="repro attempts started",
        )
        repro_summary = _run_repro_attempts(
            crash_seed=crash_seed_path,
            crash_signature=crash_summary["signature"],
            attempts=repro_attempts,
            out_dir=out_dir / "repro" / crash_seed_path.stem,
            runner_kwargs={
                **runner_kwargs,
                "repro_command": f"{guest_syz_execprog_path} -executor={guest_syz_executor_path} -repeat=0 -procs={procs} -threaded={1 if threaded else 0} -coverfile={DEFAULT_GUEST_COVER_PATH} {DEFAULT_GUEST_SEED_PATH}",
            },
        )
        crash_prog = out_dir / "crashes" / f"{crash_seed_path.stem}-{crash_summary['signature']}.prog"
        crash_prog.write_text(crash_seed_path.read_text(encoding="utf-8"), encoding="utf-8")
        _write_progress(
            out_dir,
            stage_index=total_stages,
            stage_total=total_stages,
            stage_name="repro",
            substage="summary",
            status="finished",
            seed=crash_seed_path.name,
            current=repro_summary.get("crash_count"),
            total=repro_summary.get("attempts"),
            detail=repro_summary.get("classification"),
        )

    known_bug_review = None
    if known_bug_review_path and known_bug_review_path.exists():
        known_bug_review = _load_json(known_bug_review_path)
    manual_review = generate_manual_novelty_report(
        crash_evidence_summary=crash_summary,
        candidate_evidence_summary=candidate_summary,
        reproducibility_summary=repro_summary,
        seen_signatures=seen_signatures,
    )
    if known_bug_review is None:
        known_bug_review = manual_review
    _write_json(out_dir / "crashes" / "manual_known_bug_review.json", manual_review)

    verdict = classify_net_runtime_verdict(
        preflight_ready=preflight["ready"],
        execution_evidence_summary=execution_summary,
        crash_evidence_summary=crash_summary,
        candidate_evidence_summary=candidate_summary,
        reproducibility_summary=repro_summary,
        known_bug_review=known_bug_review,
    )

    phase_summary = {
        "phases_exercised": execution_summary.get("phases_exercised", []),
        "stage_summaries": stage_summaries,
    }
    trigger_reachability = {
        "target_family_hit": execution_summary.get("target_family_hit", False),
        "trigger_phase_reached": execution_summary.get("trigger_phase_reached", False),
        "phase_reached": execution_summary.get("phase_reached", "unknown"),
    }
    crash_signatures = {
        "signatures": crash_summary.get("signatures", {}),
        "primary_signature": crash_summary.get("signature"),
        "primary_title": crash_summary.get("title"),
    }
    environment_summary = {
        "proof_mode": proof_mode,
        "proof_kernel_meta": proof_kernel_meta,
        "kernel": str(kernel),
        "disk_image": str(disk_image),
        "ssh_port": ssh_port,
        "arch": preflight.get("environment", {}).get("arch"),
        "cmdline": preflight.get("environment", {}).get("cmdline"),
        "guest_syz_execprog_path": guest_syz_execprog_path,
        "guest_syz_executor_path": guest_syz_executor_path,
        "guest_extra_append": guest_extra_append,
        "kernel_config_present": preflight.get("environment", {}).get("kernel_config_present", []),
        "kernel_config_missing": preflight.get("environment", {}).get("kernel_config_missing", []),
    }
    source_frame_summary = build_source_frame_summary(
        crash_evidence_summary=crash_summary,
        candidate_evidence_summary=candidate_summary,
        target_profile=target_profile,
        reproducibility_summary=repro_summary,
    )
    kernel_provenance = build_kernel_provenance(
        kernel=kernel,
        disk_image=disk_image,
        preflight_environment=preflight.get("environment", {}),
        proof_kernel_meta=proof_kernel_meta,
    )

    _write_json(out_dir / "campaign" / "stage_summary.json", {"stages": stage_summaries})
    _write_json(out_dir / "runtime" / "seed_result_summary.json", seed_result_summary)
    if single_seed_stage is not None:
        _write_json(out_dir / "runtime" / "single_seed_stage_summary.json", single_seed_stage)
    _write_json(out_dir / "runtime" / "execution_evidence_summary.json", execution_summary)
    _write_json(out_dir / "runtime" / "crash_evidence_summary.json", crash_summary)
    _write_json(out_dir / "runtime" / "candidate_evidence_summary.json", candidate_summary)
    _write_json(out_dir / "runtime" / "phase_summary.json", phase_summary)
    _write_json(out_dir / "runtime" / "trigger_reachability.json", trigger_reachability)
    _write_json(out_dir / "runtime" / "guest_environment_summary.json", environment_summary)
    _write_json(out_dir / "runtime" / "kernel_provenance.json", kernel_provenance)
    _write_json(out_dir / "runtime" / "source_frame_summary.json", source_frame_summary)
    _write_json(out_dir / "crashes" / "crash_signatures.json", crash_signatures)
    verdict["single_seed_result"] = single_seed_stage.get("seed_result_summary", {}).get("primary") if single_seed_stage else None
    verdict["executed_stages"] = [name for name, _ in stage_specs]
    _write_json(out_dir / "runtime" / "final_verdict.json", verdict)
    single_seed_result = verdict.get("single_seed_result")
    single_seed_dir = pathlib.Path(single_seed_result["seed_dir"]) if single_seed_result and single_seed_result.get("seed_dir") else None
    blocker_report = build_blocker_report(
        runtime_verdict=verdict,
        single_seed_result=single_seed_result,
        preflight_summary_path=out_dir / "preflight" / "preflight_summary.json",
        seed_dir=single_seed_dir,
    )
    if blocker_report is not None:
        _write_json(out_dir / "runtime" / "blocker_report.json", blocker_report)
    lab_state = classify_lab_net_state(
        runtime_verdict=verdict,
        source_frame_summary=source_frame_summary,
        reproducibility_summary=repro_summary,
        lab_context={
            "lab_only": proof_mode == "controlled",
            "lab_target_manifest": "targets/net/lab/manifest.json" if proof_mode == "controlled" else None,
        },
    )
    _write_json(out_dir / "runtime" / "lab_state.json", lab_state)
    _write_json(
        out_dir / "runtime" / "lab_run_bundle.json",
        build_lab_run_bundle(
            kernel_provenance=kernel_provenance,
            source_frame_summary=source_frame_summary,
            runtime_verdict=verdict,
            lab_state=lab_state,
            blocker_report=blocker_report,
            guest_environment_summary=environment_summary,
            single_seed_result=single_seed_result,
            seed_dir=single_seed_dir,
            out_dir=out_dir,
        ),
    )
    _write_json(out_dir / "logs" / "run_manifest.json", {
        "timestamp": _timestamp(),
        "out_dir": str(out_dir),
        "seeds_dir": str(seeds_dir),
        "stages": [name for name, _ in stage_specs],
        "artifact_roots": {name: str(out_dir / name) for name in ["preflight", "campaign", "runtime", "crashes", "repro", "logs"]},
    })
    _write_progress(
        out_dir,
        stage_index=total_stages,
        stage_total=total_stages,
        stage_name="complete",
        substage="summary",
        status="finished",
        detail=verdict.get("verdict_class"),
    )

    return {
        "preflight": preflight,
        "execution_evidence_summary": execution_summary,
        "crash_evidence_summary": crash_summary,
        "candidate_evidence_summary": candidate_summary,
        "repro_summary": repro_summary,
        "runtime_verdict": verdict,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run live nf_tables runtime validation lane")
    parser.add_argument("--state-model", required=True)
    parser.add_argument("--target-profile", required=True)
    parser.add_argument("--seeds-dir", required=True)
    parser.add_argument("--syz-execprog", default=None)
    parser.add_argument("--syz-executor", default=None)
    parser.add_argument("--kernel", required=True)
    parser.add_argument("--disk-image", required=True)
    parser.add_argument("--ssh-key", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--ssh-port", type=int, default=10022)
    parser.add_argument("--timeout-sec", type=int, default=180)
    parser.add_argument("--threaded", action="store_true", default=False)
    parser.add_argument("--procs", type=int, default=1)
    parser.add_argument("--boot-timeout", type=int, default=300)
    parser.add_argument("--extended-rounds", type=int, default=0)
    parser.add_argument("--repro-attempts", type=int, default=3)
    parser.add_argument("--stop-after-stage", default=None)
    parser.add_argument("--known-bug-review", default=None)
    parser.add_argument("--guest-syz-execprog-path", default=DEFAULT_GUEST_SYZ_EXECPROG)
    parser.add_argument("--guest-syz-executor-path", default=DEFAULT_GUEST_SYZ_EXECUTOR)
    parser.add_argument("--guest-extra-append", default=DEFAULT_GUEST_EXTRA_APPEND)
    parser.add_argument("--proof-mode", default=DEFAULT_PROOF_MODE)
    parser.add_argument("--proof-kernel-meta", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    summary = run_net_runtime_lane(
        state_model_path=pathlib.Path(args.state_model),
        target_profile_path=pathlib.Path(args.target_profile),
        seeds_dir=pathlib.Path(args.seeds_dir),
        out_dir=pathlib.Path(args.out_dir),
        syz_execprog=pathlib.Path(args.syz_execprog) if args.syz_execprog else None,
        syz_executor=pathlib.Path(args.syz_executor) if args.syz_executor else None,
        kernel=pathlib.Path(args.kernel),
        disk_image=pathlib.Path(args.disk_image),
        ssh_key=pathlib.Path(args.ssh_key),
        ssh_port=args.ssh_port,
        timeout_sec=args.timeout_sec,
        threaded=args.threaded,
        procs=args.procs,
        boot_timeout=args.boot_timeout,
        extended_rounds=args.extended_rounds,
        repro_attempts=args.repro_attempts,
        stop_after_stage=args.stop_after_stage,
        known_bug_review_path=pathlib.Path(args.known_bug_review) if args.known_bug_review else None,
        guest_syz_execprog_path=args.guest_syz_execprog_path,
        guest_syz_executor_path=args.guest_syz_executor_path,
        guest_extra_append=args.guest_extra_append,
        proof_mode=args.proof_mode,
        proof_kernel_meta_path=pathlib.Path(args.proof_kernel_meta) if args.proof_kernel_meta else None,
    )
    print(f"net runtime verdict: {summary['runtime_verdict']['verdict_class']}")
    return 0 if summary["runtime_verdict"]["verdict_class"] != "environment/setup failure" else 2


if __name__ == "__main__":
    sys.exit(main())
