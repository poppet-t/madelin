from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_WARNING = ROOT / "extractor" / "sample_warn_data.json"
UAFX_RAW_WARNING = ROOT / "uafx_fork" / "samples" / "raw_uafx_kvm_warning.json"


def run_cli(args: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def test_end_to_end_cli_pipeline(tmp_path: Path) -> None:
    candidate_path = tmp_path / "candidate.json"
    plan_path = tmp_path / "witness_plan.json"
    witness_path = tmp_path / "witness.syz"
    mock_seed_path = tmp_path / "mock_seed.json"
    mock_adapter_path = tmp_path / "mock_adapter.json"
    mock_program_path = tmp_path / "mock_program.txt"
    proof_dir = tmp_path / "proof"

    normalize = run_cli([
        "-m",
        "extractor.normalize_candidate",
        "--input",
        str(SAMPLE_WARNING),
        "--output",
        str(candidate_path),
    ])
    assert normalize.returncode == 0, normalize.stderr

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
        ]
    )
    assert emit.returncode == 0, emit.stderr

    export_seed = run_cli(
        [
            "-m",
            "runtime.export_mock_seed",
            "--candidate",
            str(candidate_path),
            "--plan",
            str(plan_path),
            "--output",
            str(mock_seed_path),
        ]
    )
    assert export_seed.returncode == 0, export_seed.stderr

    import_seed = run_cli(
        [
            "-m",
            "mock_adapter.import_seed",
            "--input",
            str(mock_seed_path),
            "--output",
            str(mock_adapter_path),
        ]
    )
    assert import_seed.returncode == 0, import_seed.stderr

    render_program = run_cli(
        [
            "-m",
            "mock_adapter.seed_to_mock_program",
            "--input",
            str(mock_seed_path),
            "--output",
            str(mock_program_path),
        ]
    )
    assert render_program.returncode == 0, render_program.stderr

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
    mock_seed = json.loads(mock_seed_path.read_text(encoding="utf-8"))
    mock_adapter = json.loads(mock_adapter_path.read_text(encoding="utf-8"))
    summary = json.loads((proof_dir / "summary.json").read_text(encoding="utf-8"))
    proof_md = (proof_dir / "proof.md").read_text(encoding="utf-8")
    witness = witness_path.read_text(encoding="utf-8")
    mock_program = mock_program_path.read_text(encoding="utf-8")

    assert candidate["candidate_id"] == plan["candidate_id"] == summary["candidate_id"] == mock_seed["candidate_id"]
    assert mock_adapter["candidate_id"] == mock_seed["candidate_id"]
    assert summary["witness_file"] == str(witness_path)
    assert candidate["candidate_id"] in proof_md
    assert candidate["candidate_id"] in witness
    assert "KVM_CREATE_VM" in mock_program or "openat$DEV" in mock_program


def test_uafx_export_and_import_cli_pipeline(tmp_path: Path) -> None:
    export_path = tmp_path / "uafx_bridge_export.json"
    candidate_path = tmp_path / "candidate.json"

    export_result = run_cli(
        [
            "-m",
            "uafx_fork.tools.export_bridge_candidate",
            "--input",
            str(UAFX_RAW_WARNING),
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
    assert candidate["analysis_context"]["kernel_area"] == "arch/arm64/kvm"
    assert candidate["status"]["supported"] is True


def test_cli_fails_nonzero_on_invalid_candidate(tmp_path: Path) -> None:
    bad_candidate_path = tmp_path / "bad_candidate.json"
    bad_candidate_path.write_text(json.dumps({"candidate_id": "cand_bad"}), encoding="utf-8")
    plan_path = tmp_path / "witness_plan.json"

    result = run_cli(["-m", "smt.solve_candidate", "--input", str(bad_candidate_path), "--output", str(plan_path)])

    assert result.returncode != 0
    assert "validation failed" in result.stderr
