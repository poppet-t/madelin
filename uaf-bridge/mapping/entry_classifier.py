"""Entry classification utilities for v1 UAF witness bridging."""

from __future__ import annotations

from typing import List


ENTRY_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("io_uring_setup", "io_uring_setup"),
    ("io_uring_register", "io_uring_register"),
    ("io_uring_enter", "io_uring_enter"),
    ("nfnetlink_rcv_batch", "netlink_send"),
    ("netlink_send", "netlink_send"),
    ("netlink_recv", "netlink_recv"),
    ("bpf", "bpf_cmd"),
    ("fsopen", "mount_api_step"),
    ("fsconfig", "mount_api_step"),
    ("fsmount", "mount_api_step"),
    ("move_mount", "mount_api_step"),
    ("open_tree", "mount_api_step"),
    ("mount_setattr", "mount_api_step"),
    ("umount", "mount_api_step"),
    ("fuse", "fuse_control"),
    ("dup", "fd_dup_or_share"),
    ("share", "fd_dup_or_share"),
    ("poll", "poll_wait"),
    ("wait", "poll_wait"),
    ("mmap", "mmap_interaction"),
    ("close", "close_teardown"),
    ("release", "close_teardown"),
    ("teardown", "close_teardown"),
    ("ioctl", "file_ioctl"),
    ("read", "file_read"),
    ("write", "file_write"),
    ("show", "sysfs_show"),
    ("store", "sysfs_store")
)

SUPPORTED_ENTRY_KINDS = {entry_kind for _, entry_kind in ENTRY_KEYWORDS}


def classify_entry(entry_func: str, entry_kind_hint: str | None = None) -> str:
    """Classify a candidate entry function into a normalized entry kind."""
    if isinstance(entry_kind_hint, str) and entry_kind_hint in SUPPORTED_ENTRY_KINDS:
        return entry_kind_hint

    lowered = entry_func.lower()
    if lowered == "nfnetlink_rcv_batch":
        return "netlink_send"
    if ("netlink" in lowered or "nfnetlink" in lowered or "nft" in lowered) and "send" in lowered:
        return "netlink_send"
    if ("netlink" in lowered or "nfnetlink" in lowered or "nft" in lowered) and any(token in lowered for token in ("recv", "dump", "get")):
        return "netlink_recv"
    if "bpf" in lowered:
        return "bpf_cmd"

    for needle, entry_kind in ENTRY_KEYWORDS:
        if needle in lowered:
            return entry_kind
    return "unknown"


def infer_entry_functions(loc0_context: List[str], loc1_context: List[str]) -> List[str]:
    """Infer likely entry function names from location contexts with stable dedupe.

    v1 stays intentionally narrow: use the first frame from each context as the likely entry.
    Unsupported entries are preserved explicitly instead of being silently dropped.
    """
    ordered: list[str] = []
    seen: set[str] = set()

    for context in (loc0_context, loc1_context):
        if not context:
            continue
        symbol = context[0]
        if not isinstance(symbol, str):
            continue
        cleaned = symbol.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)

    return ordered
