from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SYZ_ROOT = Path(__file__).resolve().parent / "fixtures" / "syzkaller"

PACK_CASES = {
    "kvm": {
        "raw_warning": ROOT / "uafx_fork" / "samples" / "raw_uafx_kvm_warning.json",
        "subsystem": "kvm",
        "witness_token": "openat$kvm(",
        "harness_token": "harness_family: kvm_arm64_timer_close_vs_run",
    },
    "io_uring": {
        "raw_warning": ROOT / "uafx_fork" / "samples" / "raw_uafx_io_uring_warning.json",
        "subsystem": "io_uring",
        "witness_token": "io_uring_enter(",
        "harness_token": "harness_family: io_uring_setup_enter_close_race",
    },
    "net": {
        "raw_warning": ROOT / "uafx_fork" / "samples" / "raw_uafx_net_warning.json",
        "subsystem": "net",
        "witness_token": "sendmsg$NFT_BATCH_DELETE",
        "harness_token": "harness_family: netlink_nft_dump_delete_race",
    },
    "bpf": {
        "raw_warning": ROOT / "uafx_fork" / "samples" / "raw_uafx_bpf_warning.json",
        "subsystem": "bpf",
        "witness_token": "bpf$LINK_DETACH",
        "harness_token": "harness_family: bpf_link_detach_close_race",
    },
    "fs": {
        "raw_warning": ROOT / "uafx_fork" / "samples" / "raw_uafx_fs_warning.json",
        "subsystem": "fs",
        "witness_token": "move_mount(",
        "harness_token": "harness_family: mount_api_move_umount_race",
    },
}


def run_cli(args: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize("pack", ["io_uring", "net", "bpf", "fs"])
def test_uafx_export_import_cli_pipeline_for_new_pack(pack: str, tmp_path: Path) -> None:
    case = PACK_CASES[pack]
    export_path = tmp_path / "uafx_bridge_export.json"
    candidate_path = tmp_path / "candidate.json"

    export_result = run_cli(
        [
            "-m",
            "uafx_fork.tools.export_bridge_candidate",
            "--input",
            str(case["raw_warning"]),
            "--output",
            str(export_path),
        ]
    )
    assert export_result.returncode == 0, export_result.stderr

    import_result = run_cli(
        [
            "-m",
            "extractor.import_uafx_bridge_export",
            "--input",
            str(export_path),
            "--output",
            str(candidate_path),
        ]
    )
    assert import_result.returncode == 0, import_result.stderr

    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    assert candidate["analysis_context"]["subsystem"] == case["subsystem"]
    assert candidate["status"]["supported"] is True


@pytest.mark.parametrize("pack", sorted(PACK_CASES))
def test_end_to_end_cli_pipeline(pack: str, tmp_path: Path) -> None:
    case = PACK_CASES[pack]
    export_path = tmp_path / "uafx_bridge_export.json"
    candidate_path = tmp_path / "candidate.json"
    plan_path = tmp_path / "witness_plan.json"
    witness_path = tmp_path / "witness.syz"
    harness_path = tmp_path / "harness.c"
    proof_dir = tmp_path / "proof"

    export_result = run_cli(
        [
            "-m",
            "uafx_fork.tools.export_bridge_candidate",
            "--input",
            str(case["raw_warning"]),
            "--output",
            str(export_path),
        ]
    )
    assert export_result.returncode == 0, export_result.stderr

    import_candidate = run_cli(
        [
            "-m",
            "extractor.import_uafx_bridge_export",
            "--input",
            str(export_path),
            "--output",
            str(candidate_path),
        ]
    )
    assert import_candidate.returncode == 0, import_candidate.stderr

    solve = run_cli(["-m", "smt.solve_candidate", "--input", str(candidate_path), "--output", str(plan_path)])
    assert solve.returncode == 0, solve.stderr

    emit = run_cli(
        [
            "-m",
            "runtime.emit_witness_syz",
            "--candidate",
            str(candidate_path),
            "--plan",
            str(plan_path),
            "--output",
            str(witness_path),
            "--syz-root",
            str(SYZ_ROOT),
        ]
    )
    assert emit.returncode == 0, emit.stderr

    validate = run_cli(
        [
            "-m",
            "runtime.validate_witness",
            "--candidate",
            str(candidate_path),
            "--plan",
            str(plan_path),
            "--witness",
            str(witness_path),
            "--syz-root",
            str(SYZ_ROOT),
        ]
    )
    assert validate.returncode == 0, validate.stderr

    harness = run_cli(
        [
            "-m",
            "harness.generate_harness",
            "--candidate",
            str(candidate_path),
            "--plan",
            str(plan_path),
            "--output",
            str(harness_path),
        ]
    )
    assert harness.returncode == 0, harness.stderr

    package = run_cli(
        [
            "-m",
            "proof.package_artifacts",
            "--candidate",
            str(candidate_path),
            "--plan",
            str(plan_path),
            "--witness",
            str(witness_path),
            "--output-dir",
            str(proof_dir),
        ]
    )
    assert package.returncode == 0, package.stderr

    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    summary = json.loads((proof_dir / "summary.json").read_text(encoding="utf-8"))
    proof_md = (proof_dir / "proof.md").read_text(encoding="utf-8")
    witness = witness_path.read_text(encoding="utf-8")
    harness_text = harness_path.read_text(encoding="utf-8")

    assert candidate["candidate_id"] == plan["candidate_id"] == summary["candidate_id"]
    assert candidate["analysis_context"]["subsystem"] == case["subsystem"]
    assert summary["witness_file"] == str(witness_path)
    assert candidate["candidate_id"] in proof_md
    assert case["witness_token"] in witness
    assert case["harness_token"] in harness_text
    assert candidate["status"]["supported"] is True
    assert plan["status"] == "sat"
    assert plan["sat"] is True


def test_cli_fails_nonzero_on_invalid_candidate(tmp_path: Path) -> None:
    bad_candidate_path = tmp_path / "bad_candidate.json"
    bad_candidate_path.write_text(json.dumps({"candidate_id": "cand_bad"}), encoding="utf-8")
    plan_path = tmp_path / "witness_plan.json"

    result = run_cli(["-m", "smt.solve_candidate", "--input", str(bad_candidate_path), "--output", str(plan_path)])

    assert result.returncode != 0
    assert "validation failed" in result.stderr
