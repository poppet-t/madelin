"""net (netlink/netfilter) specific symbol tables for subsystem-aware triage.

Provides curated sets of kernel function names, source files, and object types
that indicate netlink/netfilter subsystem involvement in crash reports. These
extend the generic focus_frame/focus_file matching from the candidate target
profile with broader subsystem context.

Use cases:
  - Distinguish "nf_tables crash but not matching this specific candidate" from
    "completely unrelated crash"
  - Recognize netfilter lifecycle patterns in KASAN reports even when the exact
    candidate frames aren't hit
  - Surface when execution reached interesting teardown/dump/delete paths
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Symbol tables
# ---------------------------------------------------------------------------

# Core nf_tables / netfilter lifecycle functions — create, update, dump, delete, teardown.
NET_LIFECYCLE_FUNCTIONS: frozenset[str] = frozenset({
    # nfnetlink dispatch
    "nfnetlink_rcv",
    "nfnetlink_rcv_batch",
    "nfnetlink_rcv_msg",
    # nf_tables table/chain/set create
    "nf_tables_newtable",
    "nf_tables_newchain",
    "nf_tables_newset",
    "nf_tables_newsetelem",
    "nf_tables_newrule",
    "nf_tables_newobj",
    "nf_tables_newflowtable",
    "nft_set_alloc",
    # nf_tables update
    "nf_tables_updtable",
    "nf_tables_updchain",
    # nf_tables get / dump
    "nf_tables_getset",
    "nf_tables_dump_set",
    "nf_tables_dump_sets",
    "nf_tables_getsetelem",
    "nf_tables_dump_setelem",
    "nf_tables_getrule",
    "nf_tables_dump_rules",
    "nf_tables_getobj",
    "nf_tables_dump_obj",
    "nf_tables_getflowtable",
    # nf_tables delete / destroy
    "nf_tables_deltable",
    "nf_tables_delchain",
    "nf_tables_delset",
    "nf_tables_delsetelem",
    "nf_tables_delrule",
    "nf_tables_delobj",
    "nf_tables_delflowtable",
    "nf_tables_destroy_set",
    "nft_set_destroy",
    "nf_tables_commit",
    "nf_tables_abort",
    # netlink socket lifecycle
    "netlink_sendmsg",
    "netlink_recvmsg",
    "netlink_dump",
    "netlink_release",
    "netlink_create",
    # generic netfilter
    "nf_register_net_hook",
    "nf_unregister_net_hook",
    "nf_hook_slow",
    "nft_do_chain",
})

# Source files known to contain core nf_tables / netfilter code paths.
NET_SOURCE_FILES: frozenset[str] = frozenset({
    "net/netfilter/nf_tables_api.c",
    "net/netfilter/nft_set_hash.c",
    "net/netfilter/nft_set_rbtree.c",
    "net/netfilter/nft_set_pipapo.c",
    "net/netfilter/nf_tables_core.c",
    "net/netfilter/nf_tables_offload.c",
    "net/netfilter/nf_tables_trace.c",
    "net/netlink/af_netlink.c",
    "net/netlink/genetlink.c",
    "net/netfilter/nfnetlink.c",
    "net/netfilter/nft_chain_filter.c",
    "net/netfilter/nft_immediate.c",
    "net/netfilter/nft_lookup.c",
    "net/netfilter/nft_dynset.c",
    "net/netfilter/core.c",
})

# Slab object types commonly associated with nf_tables UAFs.
NET_OBJECT_TYPES: frozenset[str] = frozenset({
    "nft_set",
    "nft_set_elem",
    "nft_table",
    "nft_chain",
    "nft_rule",
    "nft_object",
    "nft_flowtable",
    "nft_trans",
    "nft_ctx",
    "nf_conn",
    "netlink_sock",
})

# Functions where teardown/free races are most likely in nf_tables.
NET_TEARDOWN_FUNCTIONS: frozenset[str] = frozenset({
    "nf_tables_destroy_set",
    "nft_set_destroy",
    "nf_tables_delset",
    "nf_tables_delsetelem",
    "nf_tables_deltable",
    "nf_tables_delchain",
    "nf_tables_delrule",
    "nf_tables_delobj",
    "nf_tables_delflowtable",
    "nf_tables_commit",
    "nf_tables_abort",
    "netlink_release",
})

# Functions where concurrent use (the "use" side of UAF) is most likely.
NET_USE_FUNCTIONS: frozenset[str] = frozenset({
    "nf_tables_dump_set",
    "nf_tables_dump_sets",
    "nf_tables_dump_setelem",
    "nf_tables_getset",
    "nf_tables_getsetelem",
    "nf_tables_dump_rules",
    "nf_tables_getrule",
    "nf_tables_dump_obj",
    "nf_tables_getobj",
    "netlink_dump",
    "netlink_recvmsg",
    "nft_do_chain",
})


# ---------------------------------------------------------------------------
# Enrichment API
# ---------------------------------------------------------------------------

def enrich_crash_match(
    crash: dict[str, Any],
    base_match: dict[str, Any],
) -> dict[str, Any]:
    """Enrich a generic crash match with net-specific signals.

    Args:
        crash: parsed KASAN report from parse_kasan.parse_kasan_report()
        base_match: output of match_candidate.match_crash()

    Returns:
        dict with all base_match fields plus net-specific enrichments
    """
    crash_frames = set(crash.get("stack_frames", []))
    crash_files = set(crash.get("source_files", []))

    lifecycle_hits = crash_frames & NET_LIFECYCLE_FUNCTIONS
    file_hits = crash_files & NET_SOURCE_FILES
    teardown_hits = crash_frames & NET_TEARDOWN_FUNCTIONS
    use_hits = crash_frames & NET_USE_FUNCTIONS

    is_net_crash = bool(lifecycle_hits) or bool(file_hits)
    has_teardown_frame = bool(teardown_hits)
    has_use_frame = bool(use_hits)
    has_teardown_use_pair = has_teardown_frame and has_use_frame

    # Compute a net subsystem relevance score (0.0–1.0).
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
    enriched["net_enrichment"] = {
        "is_net_crash": is_net_crash,
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
    """Classify how relevant a crash is to netlink/netfilter as a subsystem.

    Returns one of:
      - "net_teardown_use" — both teardown and use frames present
      - "net_lifecycle"    — net lifecycle frames present
      - "net_file_only"    — only source file match, no function match
      - "unrelated"        — no net signals
    """
    crash_frames = set(crash.get("stack_frames", []))
    crash_files = set(crash.get("source_files", []))

    teardown_hits = crash_frames & NET_TEARDOWN_FUNCTIONS
    use_hits = crash_frames & NET_USE_FUNCTIONS
    lifecycle_hits = crash_frames & NET_LIFECYCLE_FUNCTIONS
    file_hits = crash_files & NET_SOURCE_FILES

    if teardown_hits and use_hits:
        return "net_teardown_use"
    if lifecycle_hits:
        return "net_lifecycle"
    if file_hits:
        return "net_file_only"
    return "unrelated"
