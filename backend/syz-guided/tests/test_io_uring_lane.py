#!/usr/bin/env python3

from __future__ import annotations

import json
import pathlib
import stat
import sys
import tempfile
import textwrap
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from seedgen.synthesize_seeds import synthesize
from state_model.build_state_model import build_state_model, build_target_profile
from runtime.io_uring_lane import run_io_uring_runtime_lane


_FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "packs" / "io_uring"


def _load_json(path: pathlib.Path) -> dict:
    with open(path) as f:
        return json.load(f)


class TestIoUringRuntimeLane(unittest.TestCase):
    def _write_exec_script(self, path: pathlib.Path, sleep_seconds: int = 0) -> None:
        script = textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            if [[ {sleep_seconds} -gt 0 ]]; then
              sleep {sleep_seconds}
            fi
            echo "fake syz-execprog run: $*"
            exit 0
            """
        )
        path.write_text(script, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)

    def _write_dmesg_script(self, path: pathlib.Path, crash: bool) -> None:
        if crash:
            body = textwrap.dedent(
                """\
                #!/usr/bin/env bash
                cat <<'LOG'
                BUG: KASAN: use-after-free in __do_sys_io_uring_enter+0x1a/0x30 io_uring/io_uring.c:123
                Read of size 8 at addr ffff0000deadbeef by task syz-executor/1234

                Call Trace:
                 __do_sys_io_uring_enter+0x1a/0x30
                 io_uring_enter+0x11/0x22

                Freed by task 1232:
                 io_uring_release+0x56/0x78
                LOG
                """
            )
        else:
            body = "#!/usr/bin/env bash\necho 'no kasan in dmesg'\n"
        path.write_text(body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)

    def _build_state_inputs(self) -> tuple[dict, dict, dict]:
        candidate = _load_json(_FIXTURES / "candidate.json")
        plan = _load_json(_FIXTURES / "witness_plan.json")
        sm = build_state_model(candidate, plan, "fixtures/packs/io_uring/candidate.json", "fixtures/packs/io_uring/witness_plan.json")
        tp = build_target_profile(candidate)
        return candidate, sm, tp

    def test_runtime_lane_emits_reports(self) -> None:
        _, sm, tp = self._build_state_inputs()
        seeds = synthesize(sm)

        with tempfile.TemporaryDirectory() as tmpdir:
            base = pathlib.Path(tmpdir)
            seeds_dir = base / "seeds"
            out_dir = base / "runtime"
            seeds_dir.mkdir()
            for seed in seeds:
                (seeds_dir / seed["name"]).write_text(seed["prog_text"], encoding="utf-8")

            state_model_path = base / "state_model_v1.json"
            target_profile_path = base / "target_profile.json"
            state_model_path.write_text(json.dumps(sm), encoding="utf-8")
            target_profile_path.write_text(json.dumps(tp), encoding="utf-8")

            execprog = base / "syz-execprog"
            executor = base / "syz-executor"
            dmesg = base / "dmesg.sh"
            self._write_exec_script(execprog)
            self._write_exec_script(executor)
            self._write_dmesg_script(dmesg, crash=True)

            result = run_io_uring_runtime_lane(
                state_model_path=state_model_path,
                target_profile_path=target_profile_path,
                seeds_dir=seeds_dir,
                out_dir=out_dir,
                syz_execprog=execprog,
                syz_executor=executor,
                dmesg_cmd=[str(dmesg)],
                timeout_sec=10,
                threaded=True,
                procs=1,
            )

            self.assertIn("runtime_verdict", result)
            self.assertTrue((out_dir / "execution_trace_summary.json").exists())
            self.assertTrue((out_dir / "candidate_alignment_report.json").exists())
            self.assertTrue((out_dir / "edge_coverage_summary.json").exists())
            self.assertTrue((out_dir / "preserved_prefix_report.json").exists())
            self.assertTrue((out_dir / "concurrency_window_report.json").exists())
            self.assertTrue((out_dir / "runtime_verdict.json").exists())
            self.assertGreaterEqual(result["execution_trace_summary"]["seed_count"], 1)

    def test_runtime_lane_timeout_classification(self) -> None:
        _, sm, tp = self._build_state_inputs()
        seeds = synthesize(sm)

        with tempfile.TemporaryDirectory() as tmpdir:
            base = pathlib.Path(tmpdir)
            seeds_dir = base / "seeds"
            out_dir = base / "runtime"
            seeds_dir.mkdir()
            for seed in seeds[:1]:
                (seeds_dir / seed["name"]).write_text(seed["prog_text"], encoding="utf-8")

            state_model_path = base / "state_model_v1.json"
            target_profile_path = base / "target_profile.json"
            state_model_path.write_text(json.dumps(sm), encoding="utf-8")
            target_profile_path.write_text(json.dumps(tp), encoding="utf-8")

            execprog = base / "syz-execprog"
            executor = base / "syz-executor"
            dmesg = base / "dmesg.sh"
            self._write_exec_script(execprog, sleep_seconds=2)
            self._write_exec_script(executor)
            self._write_dmesg_script(dmesg, crash=False)

            result = run_io_uring_runtime_lane(
                state_model_path=state_model_path,
                target_profile_path=target_profile_path,
                seeds_dir=seeds_dir,
                out_dir=out_dir,
                syz_execprog=execprog,
                syz_executor=executor,
                dmesg_cmd=[str(dmesg)],
                timeout_sec=1,
                threaded=True,
                procs=1,
            )

            self.assertEqual(result["runtime_verdict"]["verdict_class"], "hang/stall/timeout")


if __name__ == "__main__":
    unittest.main()
