from __future__ import annotations

import json
from pathlib import Path

import pytest

from extractor.import_uafx_bridge_export import import_uafx_bridge_export
from harness.generate_harness import render_harness
from mapping.entry_classifier import classify_entry
from runtime.emit_witness_syz import render_witness
from runtime.validate_witness import validate_witness
from smt.solve_candidate import solve_candidate


ROOT = Path(__file__).resolve().parents[1]
SYZ_ROOT = Path(__file__).resolve().parent / "fixtures" / "syzkaller"

PACK_CASES = {
    "io_uring": {
        "export": ROOT / "extractor" / "sample_uafx_io_uring_bridge_export.json",
        "subsystem": "io_uring",
        "entry_kind": "io_uring_enter",
        "template_id": "__do_sys_io_uring_enter:io_uring_enter:io-uring-arm64:v1",
        "witness_tokens": ["# target_pack=io_uring", "io_uring_setup(", "io_uring_enter("],
        "harness_tokens": ["harness_family: io_uring_setup_enter_close_race", "__NR_io_uring_enter"],
    },
    "net": {
        "export": ROOT / "extractor" / "sample_uafx_net_bridge_export.json",
        "subsystem": "net",
        "entry_kind": "netlink_send",
        "template_id": "nfnetlink_rcv_batch:netlink_send:net-netfilter-arm64:v1",
        "witness_tokens": ["# target_pack=net", "socket$NETLINK_NETFILTER", "sendmsg$NFT_BATCH_DELETE"],
        "harness_tokens": ["harness_family: netlink_nft_dump_delete_race", "NETLINK_NETFILTER"],
    },
    "bpf": {
        "export": ROOT / "extractor" / "sample_uafx_bpf_bridge_export.json",
        "subsystem": "bpf",
        "entry_kind": "bpf_cmd",
        "template_id": "__sys_bpf:bpf_cmd:bpf-arm64:v1",
        "witness_tokens": ["# target_pack=bpf", "bpf$MAP_CREATE", "bpf$LINK_DETACH"],
        "harness_tokens": ["harness_family: bpf_link_detach_close_race", "BPF_LINK_CREATE"],
    },
    "fs": {
        "export": ROOT / "extractor" / "sample_uafx_fs_bridge_export.json",
        "subsystem": "fs",
        "entry_kind": "mount_api_step",
        "template_id": "vfs_get_tree:mount_api_step:fs-mount-arm64:v1",
        "witness_tokens": ["# target_pack=fs", "fsopen(", "move_mount("],
        "harness_tokens": ["harness_family: mount_api_move_umount_race", "__NR_move_mount"],
    },
}


def _candidate_and_plan(pack: str) -> tuple[dict[str, object], dict[str, object]]:
    export_path = PACK_CASES[pack]["export"]
    export_payload = json.loads(export_path.read_text(encoding="utf-8"))
    candidate = import_uafx_bridge_export(export_payload, raw_file=str(export_path))
    plan = solve_candidate(candidate)
    return candidate, plan


@pytest.mark.parametrize(
    ("entry_func", "entry_kind_hint", "expected"),
    [
        ("__do_sys_io_uring_enter", None, "io_uring_enter"),
        ("nfnetlink_rcv_batch", None, "netlink_send"),
        ("__sys_bpf", None, "bpf_cmd"),
        ("vfs_get_tree", "mount_api_step", "mount_api_step"),
        ("__do_sys_dup3", None, "fd_dup_or_share"),
    ],
)
def test_classify_entry_supports_target_pack_kinds(entry_func: str, entry_kind_hint: str | None, expected: str) -> None:
    assert classify_entry(entry_func, entry_kind_hint=entry_kind_hint) == expected


@pytest.mark.parametrize("pack", sorted(PACK_CASES))
def test_import_preserves_pack_metadata(pack: str) -> None:
    candidate, _ = _candidate_and_plan(pack)
    case = PACK_CASES[pack]

    assert candidate["analysis_context"]["subsystem"] == case["subsystem"]
    assert candidate["entries"][0]["entry_kind"] == case["entry_kind"]
    assert candidate["entries"][0]["syscall_templates"][0]["template_id"] == case["template_id"]
    assert candidate["status"]["supported"] is True
    assert candidate["status"]["ready_for_smt"] is True


@pytest.mark.parametrize("pack", sorted(PACK_CASES))
def test_solve_candidate_is_deterministic_for_pack(pack: str) -> None:
    candidate, plan = _candidate_and_plan(pack)
    plan_repeat = solve_candidate(candidate)

    assert plan["ordered_steps"] == plan_repeat["ordered_steps"]
    assert plan["threads"] == plan_repeat["threads"]
    assert plan["barriers"] == plan_repeat["barriers"]
    assert plan["predicates"] == plan_repeat["predicates"]
    assert plan["execution_hints"] == plan_repeat["execution_hints"]
    assert plan["status"] == "sat"
    assert plan["sat"] is True
    assert plan["execution_hints"]["entry_selection"]["template_id"] == PACK_CASES[pack]["template_id"]


@pytest.mark.parametrize("pack", sorted(PACK_CASES))
def test_render_and_validate_witness_for_pack(pack: str) -> None:
    candidate, plan = _candidate_and_plan(pack)
    witness = render_witness(candidate, plan, syz_root=SYZ_ROOT)
    summary = validate_witness(candidate, plan, witness, syz_root=SYZ_ROOT)

    assert summary["valid"] is True
    assert summary["representative_template_id"] == PACK_CASES[pack]["template_id"]
    for token in PACK_CASES[pack]["witness_tokens"]:
        assert token in witness


@pytest.mark.parametrize("pack", sorted(PACK_CASES))
def test_render_harness_for_pack(pack: str) -> None:
    candidate, plan = _candidate_and_plan(pack)
    harness = render_harness(candidate, plan)

    assert candidate["candidate_id"] in harness
    for token in PACK_CASES[pack]["harness_tokens"]:
        assert token in harness
