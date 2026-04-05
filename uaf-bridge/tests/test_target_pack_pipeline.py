from __future__ import annotations

import json
from pathlib import Path

import pytest

from extractor.import_uafx_bridge_export import import_uafx_bridge_export
from harness.generate_harness import render_harness
from runtime.emit_witness_syz import render_witness
from runtime.validate_witness import validate_witness
from smt.solve_candidate import solve_candidate
from uafx_fork.tools.export_bridge_candidate import export_bridge_candidate


ROOT = Path(__file__).resolve().parents[1]
SYZ_ROOT = Path(__file__).resolve().parent / "fixtures" / "syzkaller"

PACK_CASES = {
    "io_uring": {
        "raw_warning": ROOT / "uafx_fork" / "samples" / "raw_uafx_io_uring_warning.json",
        "subsystem": "io_uring",
        "kernel_area": "fs/io_uring",
        "target_family": "io-uring-arm64-v1",
        "entry_kind": "io_uring_enter",
        "witness_tokens": ["io_uring_setup(", "io_uring_enter(", "close$io_uring"],
        "harness_tokens": ["io_uring_setup_enter_close_race", "__NR_io_uring_setup"],
    },
    "net": {
        "raw_warning": ROOT / "uafx_fork" / "samples" / "raw_uafx_net_warning.json",
        "subsystem": "net",
        "kernel_area": "net/netfilter",
        "target_family": "net-netfilter-arm64-v1",
        "entry_kind": "netlink_send",
        "witness_tokens": ["socket$NETLINK_NETFILTER(", "sendmsg$NFT_BATCH_CREATE(", "family=recvmsg$NETLINK_DUMP"],
        "harness_tokens": ["netlink_nft_dump_delete_race", "NETLINK_NETFILTER"],
    },
    "bpf": {
        "raw_warning": ROOT / "uafx_fork" / "samples" / "raw_uafx_bpf_warning.json",
        "subsystem": "bpf",
        "kernel_area": "kernel/bpf",
        "target_family": "bpf-arm64-v1",
        "entry_kind": "bpf_cmd",
        "witness_tokens": ["bpf$MAP_CREATE(", "bpf$PROG_LOAD(", "bpf$MAP_UPDATE_ELEM("],
        "harness_tokens": ["bpf_link_detach_close_race", "__NR_bpf"],
    },
    "fs": {
        "raw_warning": ROOT / "uafx_fork" / "samples" / "raw_uafx_fs_warning.json",
        "subsystem": "fs",
        "kernel_area": "fs/namespace",
        "target_family": "fs-mount-arm64-v1",
        "entry_kind": "mount_api_step",
        "witness_tokens": ["fsopen(", "fsmount(", "move_mount("],
        "harness_tokens": ["mount_api_move_umount_race", "__NR_fsopen"],
    },
}


@pytest.mark.parametrize("pack", sorted(PACK_CASES))
def test_raw_warning_export_import_and_pack_resolution(pack: str) -> None:
    case = PACK_CASES[pack]
    raw_warning = json.loads(Path(case["raw_warning"]).read_text(encoding="utf-8"))

    bridge_export = export_bridge_candidate(raw_warning)
    candidate = import_uafx_bridge_export(bridge_export, raw_file=str(case["raw_warning"]))

    analysis_context = candidate["analysis_context"]
    assert analysis_context["subsystem"] == case["subsystem"]
    assert analysis_context["kernel_area"] == case["kernel_area"]
    assert analysis_context["target_family"] == case["target_family"]
    assert candidate["entries"][0]["entry_kind"] == case["entry_kind"]
    assert candidate["status"]["supported"] is True


@pytest.mark.parametrize("pack", sorted(PACK_CASES))
def test_target_pack_witness_roundtrip(pack: str) -> None:
    case = PACK_CASES[pack]
    raw_warning = json.loads(Path(case["raw_warning"]).read_text(encoding="utf-8"))
    bridge_export = export_bridge_candidate(raw_warning)
    candidate = import_uafx_bridge_export(bridge_export, raw_file=str(case["raw_warning"]))
    plan = solve_candidate(candidate)

    witness = render_witness(candidate, plan, syz_root=SYZ_ROOT)
    summary = validate_witness(candidate, plan, witness, syz_root=SYZ_ROOT)

    assert summary["valid"] is True
    for token in case["witness_tokens"]:
        assert token in witness


@pytest.mark.parametrize("pack", sorted(PACK_CASES))
def test_target_pack_harness_generation(pack: str) -> None:
    case = PACK_CASES[pack]
    raw_warning = json.loads(Path(case["raw_warning"]).read_text(encoding="utf-8"))
    bridge_export = export_bridge_candidate(raw_warning)
    candidate = import_uafx_bridge_export(bridge_export, raw_file=str(case["raw_warning"]))
    plan = solve_candidate(candidate)

    harness = render_harness(candidate, plan)

    assert candidate["candidate_id"] in harness
    for token in case["harness_tokens"]:
        assert token in harness
