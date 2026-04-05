"""io_uring-specific symbol tables for subsystem-aware triage.

Provides curated sets of kernel function names, source files, and object types
that indicate io_uring subsystem involvement in crash reports. These extend the
generic focus_frame/focus_file matching from the candidate target profile with
broader subsystem context.

Use cases:
  - Distinguish "io_uring crash but not matching this specific candidate" from
    "completely unrelated crash"
  - Recognize io_uring lifecycle patterns in KASAN reports even when the exact
    candidate frames aren't hit
  - Surface when execution reached interesting io_uring teardown/use paths
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Symbol tables
# ---------------------------------------------------------------------------

# Core io_uring lifecycle functions — setup, register, enter, teardown.
IO_URING_LIFECYCLE_FUNCTIONS: frozenset[str] = frozenset({
    # setup / init
    "io_uring_setup",
    "__do_sys_io_uring_setup",
    "io_ring_ctx_alloc",
    "io_ring_ctx_alloc_and_init",
    "io_allocate_scq_urings",
    "io_sq_offload_create",
    # register
    "io_uring_register",
    "__do_sys_io_uring_register",
    "__io_uring_register",
    "io_register_files",
    "io_sqe_files_register",
    "io_sqe_buffers_register",
    # enter / submit
    "io_uring_enter",
    "__do_sys_io_uring_enter",
    "io_submit_sqes",
    "io_submit_sqe",
    "__io_submit_flush_completions",
    "io_issue_sqe",
    "io_wq_submit_work",
    # completion
    "io_complete_rw",
    "io_cqring_ev_posted",
    "__io_cqring_overflow_flush",
    # cancel / timeout
    "io_async_cancel",
    "io_timeout",
    "io_timeout_cancel",
    "io_kill_timeouts",
    # teardown / release
    "io_uring_release",
    "io_ring_ctx_free",
    "io_ring_ctx_wait_and_kill",
    "__io_uring_cancel",
    "io_uring_try_cancel_requests",
    "io_uring_clean_tctx",
    "io_uring_cancel_generic",
    "io_ring_exit_work",
    # resource management
    "io_rsrc_put_work",
    "io_rsrc_node_switch",
    "io_free_req",
    "io_put_req",
    "io_dismantle_req",
    "io_req_complete_post",
})

# Source files known to contain core io_uring code paths.
IO_URING_SOURCE_FILES: frozenset[str] = frozenset({
    "io_uring/io_uring.c",
    "io_uring/io-wq.c",
    "io_uring/rsrc.c",
    "io_uring/cancel.c",
    "io_uring/timeout.c",
    "io_uring/sqpoll.c",
    "io_uring/fdinfo.c",
    "io_uring/kbuf.c",
    "io_uring/msg_ring.c",
    "io_uring/net.c",
    "io_uring/rw.c",
    "io_uring/poll.c",
    "io_uring/openclose.c",
    "io_uring/filetable.c",
    "fs/io_uring.c",  # older kernel layout (pre-5.19)
    "fs/io-wq.c",     # older kernel layout
})

# Slab object types commonly associated with io_uring UAFs.
IO_URING_OBJECT_TYPES: frozenset[str] = frozenset({
    "io_ring_ctx",
    "io_kiocb",
    "io_rsrc_node",
    "io_rsrc_data",
    "io_mapped_ubuf",
    "io_wq_work",
    "io_sq_data",
})

# Functions where teardown/free races are most likely in io_uring.
IO_URING_TEARDOWN_FUNCTIONS: frozenset[str] = frozenset({
    "io_ring_ctx_free",
    "io_ring_ctx_wait_and_kill",
    "io_uring_release",
    "__io_uring_cancel",
    "io_uring_try_cancel_requests",
    "io_rsrc_put_work",
    "io_free_req",
    "io_put_req",
    "io_ring_exit_work",
})

# Functions where concurrent use (the "use" side of UAF) is most likely.
IO_URING_USE_FUNCTIONS: frozenset[str] = frozenset({
    "__do_sys_io_uring_enter",
    "io_uring_enter",
    "io_submit_sqes",
    "__io_submit_flush_completions",
    "io_issue_sqe",
    "io_wq_submit_work",
    "io_complete_rw",
    "__io_uring_register",
})


# ---------------------------------------------------------------------------
# Enrichment API
# ---------------------------------------------------------------------------

def enrich_crash_match(
    crash: dict[str, Any],
    base_match: dict[str, Any],
) -> dict[str, Any]:
    """Enrich a generic crash match with io_uring-specific signals.

    Args:
        crash: parsed KASAN report from parse_kasan.parse_kasan_report()
        base_match: output of match_candidate.match_crash()

    Returns:
        dict with all base_match fields plus io_uring-specific enrichments
    """
    crash_frames = set(crash.get("stack_frames", []))
    crash_files = set(crash.get("source_files", []))

    lifecycle_hits = crash_frames & IO_URING_LIFECYCLE_FUNCTIONS
    file_hits = crash_files & IO_URING_SOURCE_FILES
    teardown_hits = crash_frames & IO_URING_TEARDOWN_FUNCTIONS
    use_hits = crash_frames & IO_URING_USE_FUNCTIONS

    is_io_uring_crash = bool(lifecycle_hits) or bool(file_hits)
    has_teardown_frame = bool(teardown_hits)
    has_use_frame = bool(use_hits)
    has_teardown_use_pair = has_teardown_frame and has_use_frame

    # Compute an io_uring subsystem relevance score (0.0–1.0).
    subsystem_score = 0.0
    if lifecycle_hits:
        subsystem_score += min(len(lifecycle_hits) * 0.15, 0.45)
    if file_hits:
        subsystem_score += min(len(file_hits) * 0.10, 0.25)
    if has_teardown_use_pair:
        subsystem_score += 0.30
    elif has_teardown_frame or has_use_frame:
        subsystem_score += 0.15
    subsystem_score = min(subsystem_score, 1.0)

    enriched = dict(base_match)
    enriched["io_uring_enrichment"] = {
        "is_io_uring_crash": is_io_uring_crash,
        "subsystem_relevance_score": round(subsystem_score, 3),
        "lifecycle_frame_hits": sorted(lifecycle_hits),
        "source_file_hits": sorted(file_hits),
        "teardown_frame_hits": sorted(teardown_hits),
        "use_frame_hits": sorted(use_hits),
        "has_teardown_use_pair": has_teardown_use_pair,
    }

    return enriched


def classify_crash_subsystem_relevance(
    crash: dict[str, Any],
) -> str:
    """Classify how relevant a crash is to io_uring as a subsystem.

    Returns one of:
      - "io_uring_teardown_use" — both teardown and use frames present
      - "io_uring_lifecycle"    — io_uring lifecycle frames present
      - "io_uring_file_only"    — only source file match, no function match
      - "unrelated"             — no io_uring signals
    """
    crash_frames = set(crash.get("stack_frames", []))
    crash_files = set(crash.get("source_files", []))

    teardown_hits = crash_frames & IO_URING_TEARDOWN_FUNCTIONS
    use_hits = crash_frames & IO_URING_USE_FUNCTIONS
    lifecycle_hits = crash_frames & IO_URING_LIFECYCLE_FUNCTIONS
    file_hits = crash_files & IO_URING_SOURCE_FILES

    if teardown_hits and use_hits:
        return "io_uring_teardown_use"
    if lifecycle_hits:
        return "io_uring_lifecycle"
    if file_hits:
        return "io_uring_file_only"
    return "unrelated"
