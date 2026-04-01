#!/usr/bin/env python3
"""One-shot vm_validator orchestrator.

Sequence: preflight -> boot VM -> inject prog -> execute -> collect logs -> triage -> shutdown.

Usage:
    python -m vm_validator.run_one \
        --kernel /path/to/Image \
        --disk-image /path/to/disk.qcow2 \
        --ssh-key /path/to/id_rsa \
        --prog /path/to/seed_full_run.prog \
        --out-dir /path/to/output/ \
        [--syz-execprog /path/to/syz-execprog] \
        [--state-model /path/to/state_model_v1.json] \
        [--target-profile /path/to/target_profile.json] \
        [--ssh-port 10022]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from vm_validator.preflight import run_preflight
from vm_validator.vm_runner import boot_vm, shutdown_vm
from vm_validator.prog_injector import execute_prog
from vm_validator.log_collector import collect_dmesg, extract_kasan, save_logs


def run_one(
    kernel: pathlib.Path,
    disk_image: pathlib.Path,
    ssh_key: pathlib.Path,
    prog: pathlib.Path,
    out_dir: pathlib.Path,
    syz_execprog: pathlib.Path | None = None,
    executor_path: str | None = None,
    state_model_path: pathlib.Path | None = None,
    target_profile_path: pathlib.Path | None = None,
    ssh_port: int = 10022,
) -> dict:
    """Execute a single validation run. Returns a structured vm_run_log dict."""
    out_dir.mkdir(parents=True, exist_ok=True)
    start_time = time.monotonic()
    log: dict = {
        "candidate_id": None,
        "seed_used": prog.name,
        "vm_boot_ok": False,
        "prog_executed": False,
        "kasan_detected": False,
        "triage_verdict": None,
        "duration_seconds": 0,
        "exit_reason": "not_started",
    }

    # ── Step 1: Preflight ──
    print("[vm_validator] Running preflight checks...")
    pf = run_preflight(kernel, disk_image, ssh_key, syz_execprog)
    _write_json(pf, out_dir / "preflight_result.json")

    if not pf["ready"]:
        failed = [c for c in pf["checks"] if not c["ok"]]
        errors = "; ".join(c["error"] for c in failed)
        print(f"[vm_validator] Preflight FAILED: {errors}")
        log["exit_reason"] = "preflight_failed"
        log["duration_seconds"] = round(time.monotonic() - start_time, 1)
        _write_json(log, out_dir / "vm_run_log.json")
        return log

    print("[vm_validator] Preflight passed.")

    # ── Step 2: Boot VM ──
    print(f"[vm_validator] Booting QEMU TCG (ssh_port={ssh_port})...")
    console_log = out_dir / "console.log"
    boot = boot_vm(
        kernel=kernel,
        disk_image=disk_image,
        ssh_port=ssh_port,
        console_log=console_log,
    )

    if not boot["ok"]:
        print(f"[vm_validator] Boot FAILED: {boot['error']}")
        log["exit_reason"] = "boot_failed"
        log["duration_seconds"] = round(time.monotonic() - start_time, 1)
        _write_json(log, out_dir / "vm_run_log.json")
        # Clean up QEMU if it's still running.
        if boot["process"] is not None:
            shutdown_vm(boot["process"], ssh_port=ssh_port)
        return log

    proc = boot["process"]
    log["vm_boot_ok"] = True
    print(f"[vm_validator] VM booted. SSH ready in {boot['ssh_ready']['elapsed']}s.")

    try:
        # ── Step 3: Inject and execute prog ──
        if syz_execprog is not None:
            print(f"[vm_validator] Injecting {prog.name}...")
            exec_result = execute_prog(
                syz_execprog=syz_execprog,
                prog_file=prog,
                ssh_port=ssh_port,
                ssh_key=ssh_key,
                executor_path=executor_path,
            )

            if exec_result["ok"]:
                log["prog_executed"] = True
                print(f"[vm_validator] Prog executed (exit_code={exec_result['exit_code']}).")
            else:
                print(f"[vm_validator] Prog execution failed: {exec_result['error']}")

            # Save execprog output even on failure.
            execprog_stdout = exec_result.get("stdout", "")
            execprog_stderr = exec_result.get("stderr", "")
        else:
            print("[vm_validator] No syz-execprog provided — skipping injection.")
            execprog_stdout = ""
            execprog_stderr = ""

        # ── Step 4: Collect logs ──
        print("[vm_validator] Collecting dmesg...")
        dmesg_result = collect_dmesg(ssh_port=ssh_port, ssh_key=ssh_key)
        dmesg_text = dmesg_result.get("dmesg", "")
        kasan_excerpt = extract_kasan(dmesg_text)

        if kasan_excerpt:
            log["kasan_detected"] = True
            print("[vm_validator] KASAN report detected in dmesg.")
        else:
            print("[vm_validator] No KASAN report found in dmesg.")

        save_logs(
            out_dir=out_dir,
            dmesg=dmesg_text,
            kasan_excerpt=kasan_excerpt,
            execprog_stdout=execprog_stdout,
            execprog_stderr=execprog_stderr,
        )

        # ── Step 5: Triage (if artifacts available) ──
        if state_model_path and target_profile_path and (kasan_excerpt or dmesg_text):
            log["triage_verdict"] = _run_triage(
                crash_text=kasan_excerpt or dmesg_text,
                state_model_path=state_model_path,
                target_profile_path=target_profile_path,
                out_dir=out_dir,
            )

        log["exit_reason"] = "clean_shutdown"

    finally:
        # ── Step 6: Shutdown ──
        print("[vm_validator] Shutting down VM...")
        shutdown_result = shutdown_vm(proc, ssh_port=ssh_port, ssh_key=ssh_key)
        print(f"[vm_validator] VM stopped (method={shutdown_result['method']}).")

    log["duration_seconds"] = round(time.monotonic() - start_time, 1)
    _write_json(log, out_dir / "vm_run_log.json")
    print(f"[vm_validator] Done. Duration: {log['duration_seconds']}s. Output: {out_dir}")
    return log


def _run_triage(
    crash_text: str,
    state_model_path: pathlib.Path,
    target_profile_path: pathlib.Path,
    out_dir: pathlib.Path,
) -> str | None:
    """Invoke existing triage pipeline. Returns verdict string or None."""
    try:
        from triage.report import build_triage_report

        with open(state_model_path) as f:
            sm = json.load(f)
        with open(target_profile_path) as f:
            tp = json.load(f)

        report = build_triage_report(crash_text, tp, sm)
        _write_json(report, out_dir / "triage_report_v1.json")
        verdict = report.get("verdict", "unknown")
        print(f"[vm_validator] Triage verdict: {verdict}")
        return verdict

    except Exception as exc:
        print(f"[vm_validator] Triage failed: {exc}")
        return None


def _write_json(data: dict, path: pathlib.Path) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="One-shot vm_validator run")
    parser.add_argument("--kernel", required=True, help="Path to arm64 kernel Image")
    parser.add_argument("--disk-image", required=True, help="Path to arm64 root disk (qcow2)")
    parser.add_argument("--ssh-key", required=True, help="Path to SSH private key")
    parser.add_argument("--prog", required=True, help="Path to .prog seed file")
    parser.add_argument("--out-dir", required=True, help="Output directory")
    parser.add_argument("--syz-execprog", default=None, help="Path to syz-execprog binary")
    parser.add_argument("--executor-path", default=None, help="Guest-side path to syz-executor (e.g. /root/syzkaller/syz-executor)")
    parser.add_argument("--state-model", default=None, help="Path to state_model_v1.json (for triage)")
    parser.add_argument("--target-profile", default=None, help="Path to target_profile.json (for triage)")
    parser.add_argument("--ssh-port", type=int, default=10022, help="SSH forwarding port (default: 10022)")
    args = parser.parse_args()

    log = run_one(
        kernel=pathlib.Path(args.kernel),
        disk_image=pathlib.Path(args.disk_image),
        ssh_key=pathlib.Path(args.ssh_key),
        prog=pathlib.Path(args.prog),
        out_dir=pathlib.Path(args.out_dir),
        syz_execprog=pathlib.Path(args.syz_execprog) if args.syz_execprog else None,
        executor_path=args.executor_path,
        state_model_path=pathlib.Path(args.state_model) if args.state_model else None,
        target_profile_path=pathlib.Path(args.target_profile) if args.target_profile else None,
        ssh_port=args.ssh_port,
    )

    if log.get("exit_reason") == "preflight_failed":
        return 2
    if not log.get("vm_boot_ok"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
