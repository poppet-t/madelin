from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFY_CANDIDATE_SCRIPT = REPO_ROOT / "scripts" / "verify_candidate.sh"
VERIFY_BATCH_SCRIPT = REPO_ROOT / "scripts" / "verify_batch.sh"
E2E_WITNESS_SMOKE_SCRIPT = REPO_ROOT / "scripts" / "e2e_witness_smoke.sh"
E2E_HARNESS_SMOKE_SCRIPT = REPO_ROOT / "scripts" / "e2e_harness_smoke.sh"


def _write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_executable(path: Path, content: str) -> Path:
    _write_text(path, content)
    path.chmod(0o755)
    return path


def _candidate_payload(candidate_id: str) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "analysis_context": {"kernel_area": "arch/arm64/kvm"},
        "loc0": {"function": "kvm_timer_vcpu_terminate", "file": "arch/arm64/kvm/arch_timer.c", "line": 812},
        "loc1": {"function": "kvm_timer_should_fire", "file": "arch/arm64/kvm/arch_timer.c", "line": 923},
        "entries": [{"entry_func": "kvm_vcpu_ioctl"}],
    }


def _write_bridge_stubs(root: Path) -> dict[str, str]:
    solve = _write_executable(
        root / "solve_candidate.py",
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "import sys",
                "from pathlib import Path",
                "args = sys.argv[1:]",
                "input_path = Path(args[args.index('--input') + 1])",
                "output_path = Path(args[args.index('--output') + 1])",
                "candidate = json.loads(input_path.read_text(encoding='utf-8'))",
                "plan = {",
                "    'schema_version': 'witness_plan/v1',",
                "    'candidate_id': candidate['candidate_id'],",
                "    'sat': True,",
                "    'status': 'sat',",
                "    'ordered_steps': [],",
                "    'threads': [],",
                "    'barriers': [],",
                "    'predicates': [],",
                "    'execution_hints': {'min_threads': 1},",
                "}",
                "output_path.parent.mkdir(parents=True, exist_ok=True)",
                "output_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + '\\n', encoding='utf-8')",
            ]
        ),
    )
    emit_witness = _write_executable(
        root / "emit_witness.py",
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import sys",
                "from pathlib import Path",
                "args = sys.argv[1:]",
                "output_path = Path(args[args.index('--output') + 1])",
                "output_path.parent.mkdir(parents=True, exist_ok=True)",
                "output_path.write_text(\"r0 = openat$KVM(0xffffffffffffff9c, &AUTO='/dev/kvm\\\\x00', 0x2, 0x0)\\n\", encoding='utf-8')",
            ]
        ),
    )
    generate_harness = _write_executable(
        root / "generate_harness.py",
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import sys",
                "from pathlib import Path",
                "args = sys.argv[1:]",
                "output_path = Path(args[args.index('--output') + 1])",
                "output_path.parent.mkdir(parents=True, exist_ok=True)",
                "output_path.write_text('#include <stdio.h>\\nint main(void) { return 0; }\\n', encoding='utf-8')",
            ]
        ),
    )
    export_mock_seed = _write_executable(
        root / "export_mock_seed.py",
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "import sys",
                "from pathlib import Path",
                "args = sys.argv[1:]",
                "candidate_path = Path(args[args.index('--candidate') + 1])",
                "output_path = Path(args[args.index('--output') + 1])",
                "candidate = json.loads(candidate_path.read_text(encoding='utf-8'))",
                "seed = {",
                "    'seed_version': 'mock_seed/v1',",
                "    'candidate_id': candidate['candidate_id'],",
                "    'target': 'linux',",
                "    'arch': 'arm64',",
                "    'subsystem': 'kvm',",
                "    'flow': 'Con',",
                "    'threads': 2,",
                "    'abstract_steps': ['escape', 'free', 'use'],",
                "    'entries': [{'entry_func': 'kvm_vcpu_ioctl', 'entry_kind': 'file_ioctl', 'confidence': 'grounded', 'supported': True, 'support_level': 'grounded', 'template_ids': ['tmpl0'], 'notes': []}],",
                "    'setup_sequence': [",
                "        {'family': 'openat$KVM', 'grounding': 'grounded', 'kind': 'syscall', 'resource_effect': 'fd_kvm', 'stage': 'setup', 'text': 'openat$KVM(...)'},",
                "        {'family': 'KVM_CREATE_VM', 'grounding': 'grounded', 'kind': 'syscall', 'resource_effect': 'fd_vm', 'stage': 'setup', 'text': 'ioctl$KVM_CREATE_VM(...)'},",
                "        {'family': 'KVM_CREATE_VCPU', 'grounding': 'grounded', 'kind': 'syscall', 'resource_effect': 'fd_vcpu', 'stage': 'setup', 'text': 'ioctl$KVM_CREATE_VCPU(...)'},",
                "    ],",
                "    'trigger_sequence': [",
                "        {'family': 'KVM_RUN', 'grounding': 'grounded', 'kind': 'syscall', 'resource_effect': None, 'stage': 'trigger', 'text': 'ioctl$KVM_RUN(...)'},",
                "    ],",
                "    'focus_syscall_families': ['KVM_RUN'],",
                "    'ordering': [{'before': 'escape', 'after': 'use', 'reason': 'demo'}],",
                "    'predicates': [{'grounding': 'grounded', 'must_hold_at': 'init_resource', 'name': 'kvm_fd_ready'}],",
                "    'ordered_steps': [{'event': 'escape', 'step_index': 0, 'thread_id': 0, 'timestamp': 0}],",
                "    'resource_dependencies': ['/dev/kvm'],",
                "    'thread_hints': {'prefer_collide': True, 'schedule_style': 'two-thread-collision', 'thread_step_counts': [{'thread_id': 0, 'step_count': 1}]},",
                "    'mutation_hints': {'focus_syscall_families': ['KVM_RUN'], 'keep_ordering_edges': ['escape->use'], 'mutate_near_steps': ['use'], 'prefer_collide': True, 'prefer_two_thread_schedule': True, 'preserve_prefix_len': 3, 'stable_prefix_resources': ['/dev/kvm']},",
                "    'confidence': {'mapping_confidence': 'grounded', 'ready_for_smt': True, 'supported': True, 'unsupported_reasons': []},",
                "    'debug': {'loc0': candidate['loc0'], 'loc1': candidate['loc1'], 'notes': ['stub'], 'same_object': True, 'selected_entry_func': 'kvm_vcpu_ioctl', 'selected_entry_kind': 'file_ioctl', 'selected_template_id': 'tmpl0'},",
                "    'source': {'producer': 'uaf-bridge', 'normalizer': 'stub', 'uafx_warning_id': 'warn_demo', 'witness_plan_status': 'sat'},",
                "}",
                "output_path.parent.mkdir(parents=True, exist_ok=True)",
                "output_path.write_text(json.dumps(seed, indent=2, sort_keys=True) + '\\n', encoding='utf-8')",
            ]
        ),
    )
    import_seed = _write_executable(
        root / "import_seed.py",
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "import sys",
                "from pathlib import Path",
                "args = sys.argv[1:]",
                "seed_path = Path(args[0])",
                "output_dir = Path(args[args.index('--output-dir') + 1])",
                "seed = json.loads(seed_path.read_text(encoding='utf-8'))",
                "(output_dir / 'input').mkdir(parents=True, exist_ok=True)",
                "(output_dir / 'relations').mkdir(parents=True, exist_ok=True)",
                "(output_dir / 'preview').mkdir(parents=True, exist_ok=True)",
                "(output_dir / 'input' / 'seed_00.prog').write_text('openat$KVM(0)\\n', encoding='utf-8')",
                "(output_dir / 'relations' / 'bridge_seed.relations').write_text('openat$KVM,ioctl$KVM_CREATE_VM\\n', encoding='utf-8')",
                "(output_dir / 'bias.json').write_text(json.dumps({'candidate_id': seed['candidate_id']}, indent=2, sort_keys=True) + '\\n', encoding='utf-8')",
                "(output_dir / 'imported_seed.json').write_text(json.dumps(seed, indent=2, sort_keys=True) + '\\n', encoding='utf-8')",
                "(output_dir / 'preview' / 'summary.json').write_text(json.dumps({'candidate_id': seed['candidate_id']}, indent=2, sort_keys=True) + '\\n', encoding='utf-8')",
            ]
        ),
    )
    return {
        "VERIFY_SOLVE_CANDIDATE_CMD": str(solve),
        "VERIFY_EMIT_WITNESS_CMD": str(emit_witness),
        "VERIFY_GENERATE_HARNESS_CMD": str(generate_harness),
        "VERIFY_EXPORT_MOCK_SEED_CMD": str(export_mock_seed),
        "VERIFY_IMPORT_SEED_CMD": str(import_seed),
    }


def _write_runtime_stubs(root: Path) -> dict[str, str]:
    harness = _write_executable(
        root / "run_harness.py",
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import sys
            from pathlib import Path

            args = sys.argv[1:]
            output_dir = Path(args[args.index('--output-dir') + 1])
            output_dir.mkdir(parents=True, exist_ok=True)
            verdict = {
                'candidate_id': 'cand_demo',
                'verdict': 'REACHED_NO_CRASH',
                'confidence': 'low',
                'execution': {'execution_mode': 'harness_timing_sweep'},
                'evidence': {},
                'timestamp': '2026-03-23T00:00:00Z',
            }
            (output_dir / 'verdict.json').write_text(json.dumps(verdict, indent=2, sort_keys=True) + '\\n', encoding='utf-8')
            print('stub harness complete')
            """
        ),
    )
    witness = _write_executable(
        root / "run_witness.py",
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import sys
            from pathlib import Path

            args = sys.argv[1:]
            candidate_path = Path(args[args.index('--candidate') + 1])
            output_dir = Path(args[args.index('--output-dir') + 1])
            candidate = json.loads(candidate_path.read_text(encoding='utf-8'))
            output_dir.mkdir(parents=True, exist_ok=True)
            verdict = {
                'candidate_id': candidate['candidate_id'],
                'verdict': 'CONFIRMED',
                'confidence': 'high',
                'execution': {'execution_mode': 'witness_remote'},
                'evidence': {},
                'timestamp': '2026-03-23T00:00:00Z',
            }
            (output_dir / 'verdict.json').write_text(json.dumps(verdict, indent=2, sort_keys=True) + '\\n', encoding='utf-8')
            print('stub witness complete')
            """
        ),
    )
    fuzz = _write_executable(
        root / "run_fuzz.py",
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import sys
            from pathlib import Path

            args = sys.argv[1:]
            output_dir = Path(args[args.index('--output-dir') + 1])
            seed_workdir = Path(args[args.index('--seed-workdir') + 1])
            output_dir.mkdir(parents=True, exist_ok=True)
            output_dir.joinpath('saw-seed-workdir.txt').write_text(str(seed_workdir), encoding='utf-8')
            imported_seed = json.loads((seed_workdir / 'imported_seed.json').read_text(encoding='utf-8'))
            verdict = {
                'candidate_id': imported_seed['candidate_id'],
                'verdict': 'SETUP_FAILED',
                'confidence': 'medium',
                'execution': {'execution_mode': 'seeded_fuzz'},
                'evidence': {},
                'timestamp': '2026-03-23T00:00:00Z',
            }
            (output_dir / 'verdict.json').write_text(json.dumps(verdict, indent=2, sort_keys=True) + '\\n', encoding='utf-8')
            print('stub fuzz complete')
            """
        ),
    )
    return {
        "VERIFY_RUN_HARNESS_SCRIPT": str(harness),
        "VERIFY_RUN_WITNESS_SCRIPT": str(witness),
        "VERIFY_RUN_FUZZ_SCRIPT": str(fuzz),
    }


class VerifierWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="verify-workflow-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _base_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(_write_bridge_stubs(self.tmpdir / "bridge-stubs"))
        env.update(_write_runtime_stubs(self.tmpdir / "runtime-stubs"))
        return env

    def test_shell_scripts_have_valid_syntax(self) -> None:
        for script in (
            VERIFY_CANDIDATE_SCRIPT,
            VERIFY_BATCH_SCRIPT,
            E2E_WITNESS_SMOKE_SCRIPT,
            E2E_HARNESS_SMOKE_SCRIPT,
        ):
            with self.subTest(script=script.name):
                proc = subprocess.run(["bash", "-n", str(script)], cwd=REPO_ROOT, capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_verify_candidate_all_stops_after_confirmed_witness(self) -> None:
        candidate_path = _write_text(
            self.tmpdir / "cand_demo.json",
            json.dumps(_candidate_payload("cand_demo"), indent=2, sort_keys=True) + "\n",
        )
        ssh_key = _write_text(self.tmpdir / "id_rsa", "fake-key")
        disk_image = _write_text(self.tmpdir / "disk.img", "fake-disk")
        kernel_image = _write_text(self.tmpdir / "Image", "fake-kernel")
        artifacts_root = self.tmpdir / "verdicts"

        proc = subprocess.run(
            [
                "bash",
                str(VERIFY_CANDIDATE_SCRIPT),
                "--candidate",
                str(candidate_path),
                "--strategy",
                "all",
                "--artifacts-root",
                str(artifacts_root),
                "--target-host",
                "root@fake-target",
                "--ssh-key",
                str(ssh_key),
                "--disk-image",
                str(disk_image),
                "--kernel-image",
                str(kernel_image),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=self._base_env(),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

        candidate_dir = artifacts_root / "cand_demo"
        summary = json.loads((candidate_dir / "summary.json").read_text(encoding="utf-8"))
        verdict = json.loads((candidate_dir / "verdict.json").read_text(encoding="utf-8"))

        self.assertEqual(summary["final_verdict"], "CONFIRMED")
        self.assertEqual(summary["selected_strategy"], "witness")
        self.assertEqual([item["strategy"] for item in summary["strategies_attempted"]], ["harness", "witness"])
        self.assertEqual(verdict["verdict"], "CONFIRMED")
        self.assertTrue((candidate_dir / "candidate.json").is_file())
        self.assertTrue((candidate_dir / "witness_plan.json").is_file())
        self.assertTrue((candidate_dir / "witness.syz").is_file())
        self.assertTrue((candidate_dir / "harness.c").is_file())
        self.assertFalse((candidate_dir / "strategies" / "fuzz").exists())

    def test_verify_candidate_fuzz_strategy_prepares_seed_workdir(self) -> None:
        candidate_path = _write_text(
            self.tmpdir / "cand_fuzz.json",
            json.dumps(_candidate_payload("cand_fuzz"), indent=2, sort_keys=True) + "\n",
        )
        ssh_key = _write_text(self.tmpdir / "id_rsa", "fake-key")
        disk_image = _write_text(self.tmpdir / "disk.img", "fake-disk")
        kernel_image = _write_text(self.tmpdir / "Image", "fake-kernel")
        artifacts_root = self.tmpdir / "verdicts"

        proc = subprocess.run(
            [
                "bash",
                str(VERIFY_CANDIDATE_SCRIPT),
                "--candidate",
                str(candidate_path),
                "--strategy",
                "fuzz",
                "--artifacts-root",
                str(artifacts_root),
                "--ssh-key",
                str(ssh_key),
                "--disk-image",
                str(disk_image),
                "--kernel-image",
                str(kernel_image),
                "--fuzz-max-seconds",
                "5",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=self._base_env(),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

        candidate_dir = artifacts_root / "cand_fuzz"
        summary = json.loads((candidate_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["selected_strategy"], "fuzz")
        self.assertEqual(summary["final_verdict"], "SETUP_FAILED")
        self.assertTrue((candidate_dir / "mock_seed.json").is_file())
        self.assertTrue((candidate_dir / "seed_workdir" / "imported_seed.json").is_file())
        self.assertTrue((candidate_dir / "strategies" / "fuzz" / "saw-seed-workdir.txt").is_file())

    def test_verify_batch_writes_aggregate_summary(self) -> None:
        candidates_dir = self.tmpdir / "candidates"
        _write_text(
            candidates_dir / "cand_alpha.json",
            json.dumps(_candidate_payload("cand_alpha"), indent=2, sort_keys=True) + "\n",
        )
        _write_text(
            candidates_dir / "cand_beta.json",
            json.dumps(_candidate_payload("cand_beta"), indent=2, sort_keys=True) + "\n",
        )
        ssh_key = _write_text(self.tmpdir / "id_rsa", "fake-key")
        artifacts_root = self.tmpdir / "verdicts"

        proc = subprocess.run(
            [
                "bash",
                str(VERIFY_BATCH_SCRIPT),
                "--candidates-dir",
                str(candidates_dir),
                "--strategy",
                "witness",
                "--artifacts-root",
                str(artifacts_root),
                "--target-host",
                "fake-target",
                "--ssh-key",
                str(ssh_key),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=self._base_env(),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

        summary = json.loads((artifacts_root / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["candidates_total"], 2)
        self.assertEqual(summary["counts"]["CONFIRMED"], 2)
        self.assertEqual(len(summary["candidates"]), 2)
        self.assertTrue((artifacts_root / "cand_alpha" / "verdict.json").is_file())
        self.assertTrue((artifacts_root / "cand_beta" / "summary.json").is_file())


if __name__ == "__main__":
    unittest.main()
