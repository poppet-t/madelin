from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .corpus import seed_to_initial_programs
from .policy import build_mutation_bias, build_relation_lines
from .schema import validate_seed


def load_bridge_seed(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("mock_seed input must be a JSON object")
    validate_seed(payload)
    return payload


def _reset_generated_artifacts(out: Path) -> None:
    for directory in (out / "input", out / "relations", out / "preview"):
        shutil.rmtree(directory, ignore_errors=True)

    for file_path in (out / "bias.json", out / "imported_seed.json"):
        file_path.unlink(missing_ok=True)


def import_bridge_seed(seed_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    seed = load_bridge_seed(seed_path)
    out = Path(output_dir)
    _reset_generated_artifacts(out)
    input_dir = out / "input"
    relation_dir = out / "relations"
    preview_dir = out / "preview"
    input_dir.mkdir(parents=True, exist_ok=True)
    relation_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)

    programs = seed_to_initial_programs(seed)
    for idx, program in enumerate(programs):
        (input_dir / f"seed_{idx:02d}.prog").write_text(program, encoding="utf-8")

    relation_lines = build_relation_lines(seed)
    relations_path = relation_dir / "bridge_seed.relations"
    relations_path.write_text("\n".join(relation_lines) + ("\n" if relation_lines else ""), encoding="utf-8")

    bias = build_mutation_bias(seed)
    bias_path = out / "bias.json"
    bias_path.write_text(json.dumps(bias, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    imported_seed_path = out / "imported_seed.json"
    imported_seed_path.write_text(json.dumps(seed, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    preview = {
        "import_version": "bridge_seed_import/v1",
        "candidate_id": seed["candidate_id"],
        "program_count": len(programs),
        "input_dir": str(input_dir),
        "relations_file": str(relations_path),
        "bias_file": str(bias_path),
        "target": f"{seed['target']}/{seed['arch']}",
        "subsystem": seed["subsystem"],
        "flow": seed["flow"],
        "threads": seed["threads"],
        "setup_prefix_len": bias["preserve_prefix_len"],
        "focus_syscall_families": bias["focus_syscall_families"],
        "prefer_collide": bias["prefer_collide"],
    }
    (preview_dir / "summary.json").write_text(json.dumps(preview, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (preview_dir / "program_preview.txt").write_text(
        "\n---\n".join(programs) + ("\n" if programs else ""), encoding="utf-8"
    )
    return preview
