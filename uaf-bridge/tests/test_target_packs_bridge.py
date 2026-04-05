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
        "bridge_export": ROOT / "extractor" / "sample_uafx_io_uring_bridge_export.json",
        "target_family": "io-uring-arm64-v1",
        "entry_kind": "io_uring_enter",
        "witness_markers": ["# target_pack=io_uring", "io_uring_setup(", "io_uring_enter("],
        "harness_markers": ["harness_family: io_uring_setup_enter_close_race", "__NR_io_uring_enter", "close(ring_fd)"],
    },
    "net": {
        "raw_warning": ROOT / "uafx_fork" / "samples" / "raw_uafx_net_warning.json",
        "bridge_export": ROOT / "extractor" / "sample_uafx_net_bridge_export.json",
        "target_family": "net-netfilter-arm64-v1",
        "entry_kind": "netlink_send",
        "witness_markers": ["# target_pack=net", "socket$NETLINK_NETFILTER(", "sendmsg$NFT_BATCH_DELETE("],
        "harness_markers": ["harness_family: netlink_nft_dump_delete_race", "NETLINK_NETFILTER", "recvmsg(nl_fd"],
    },
    "bpf": {
        "raw_warning": ROOT / "uafx_fork" / "samples" / "raw_uafx_bpf_warning.json",
        "bridge_export": ROOT / "extractor" / "sample_uafx_bpf_bridge_export.json",
        "target_family": "bpf-arm64-v1",
        "entry_kind": "bpf_cmd",
        "witness_markers": ["# target_pack=bpf", "bpf$MAP_CREATE(", "bpf$LINK_DETACH("],
        "harness_markers": ["harness_family: bpf_link_detach_close_race", "__NR_bpf", "close(link_fd)"],
    },
    "fs": {
        "raw_warning": ROOT / "uafx_fork" / "samples" / "raw_uafx_fs_warning.json",
        "bridge_export": ROOT / "extractor" / "sample_uafx_fs_bridge_export.json",
        "target_family": "fs-mount-arm64-v1",
        "entry_kind": "mount_api_step",
        "witness_markers": ["# target_pack=fs", "fsopen(", "umount2("],
        "harness_markers": ["harness_family: mount_api_move_umount_race", "__NR_move_mount", "close(mount_fd)"],
    },
}


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate_and_plan(pack: str) -> tuple[dict[str, object], dict[str, object]]:
    export_payload = _load_json(PACK_CASES[pack]["bridge_export"])
    candidate = import_uafx_bridge_export(export_payload, raw_file=str(PACK_CASES[pack]["bridge_export"]))
    plan = solve_candidate(candidate)
    return candidate, plan


@pytest.mark.parametrize("pack", PACK_CASES)
def test_uafx_export_preserves_target_context(pack: str) -> None:
    raw_warning = _load_json(PACK_CASES[pack]["raw_warning"])
    export_payload = export_bridge_candidate(raw_warning)

    assert export_payload["subsystem"] == pack
    assert export_payload["target_family"] == PACK_CASES[pack]["target_family"]
    assert export_payload["entry_summary"]["entry_candidates"][0]["entry_kind_hint"] == PACK_CASES[pack]["entry_kind"]


@pytest.mark.parametrize("pack", PACK_CASES)
def test_imported_target_pack_candidate_renders_and_validates_witness(pack: str) -> None:
    candidate, plan = _candidate_and_plan(pack)
    witness = render_witness(candidate, plan, syz_root=SYZ_ROOT)
    summary = validate_witness(candidate, plan, witness, syz_root=SYZ_ROOT)

    assert candidate["analysis_context"]["subsystem"] == pack
    assert candidate["analysis_context"]["target_family"] == PACK_CASES[pack]["target_family"]
    assert candidate["entries"][0]["entry_kind"] == PACK_CASES[pack]["entry_kind"]
    assert summary["valid"] is True
    for marker in PACK_CASES[pack]["witness_markers"]:
        assert marker in witness


@pytest.mark.parametrize("pack", PACK_CASES)
def test_imported_target_pack_candidate_renders_generic_harness(pack: str) -> None:
    candidate, plan = _candidate_and_plan(pack)
    harness = render_harness(candidate, plan)

    assert candidate["candidate_id"] in harness
    for marker in PACK_CASES[pack]["harness_markers"]:
        assert marker in harness
