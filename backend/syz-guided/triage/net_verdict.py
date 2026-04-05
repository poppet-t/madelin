from __future__ import annotations

from typing import Any


VERDICT_CLASSES = {
    "environment/setup failure",
    "target not reached",
    "target reached, no crash",
    "unrelated crash",
    "candidate-correlated live crash",
    "reproducible kernel bug candidate",
    "novelty-unchecked bug candidate",
    "known/likely-duplicate crash candidate",
}

LAB_VERDICT_CLASSES = {
    "confirmed lab bug",
    "candidate-correlated crash",
    "no bug confirmed; exact blocker",
    "patch candidate for reproduced lab bug",
}


def build_execution_evidence(
    *,
    seed: str,
    calls: list[str],
    phase_reached: str,
    phase_progress: float,
    prefix_valid: bool,
    resource_chain_intact: bool,
    trigger_phase_reached: bool,
) -> dict[str, Any]:
    expected_lifecycle = {
        "socket$NETLINK_NETFILTER": "bootstrap",
        "sendmsg$NFT_BATCH_CREATE": "configure",
        "sendmsg$NFT_BATCH_UPDATE": "configure",
        "recvmsg$NETLINK_DUMP": "trigger",
        "sendmsg$NFT_BATCH_DELETE": "trigger",
        "close$NETLINK_NETFILTER": "trigger",
    }
    hit_calls = [call for call in calls if call in expected_lifecycle]
    phases_exercised = sorted({expected_lifecycle[call] for call in hit_calls})
    return {
        "seed": seed,
        "target_family_hit": "socket$NETLINK_NETFILTER" in calls,
        "phases_exercised": phases_exercised,
        "phase_reached": phase_reached,
        "phase_progress": round(phase_progress, 3),
        "prefix_preserved": prefix_valid,
        "resource_chain_intact": resource_chain_intact,
        "trigger_phase_reached": trigger_phase_reached,
        "lifecycle_calls_seen": hit_calls,
        "execution_quality": "high"
        if prefix_valid and resource_chain_intact and trigger_phase_reached
        else "partial"
        if "socket$NETLINK_NETFILTER" in calls
        else "missing-target",
    }


def build_crash_evidence(
    *,
    crash: dict[str, Any] | None,
    exec_result: dict[str, Any],
) -> dict[str, Any]:
    if crash is None:
        return {
            "crash_detected": False,
            "crash_kind": "timeout" if exec_result.get("timed_out") else "none",
            "real_crash_signal": False,
            "title": None,
            "signature": None,
            "top_frames": [],
            "source_files": [],
        }
    return {
        "crash_detected": True,
        "crash_kind": crash.get("kind"),
        "real_crash_signal": bool(crash.get("is_real_crash_signal")),
        "title": crash.get("title"),
        "signature": crash.get("signature"),
        "top_frames": crash.get("top_frames", []),
        "source_files": crash.get("source_files", []),
        "bug_type": crash.get("bug_type"),
    }


def build_candidate_evidence(
    *,
    candidate_match: dict[str, Any],
    target_profile: dict[str, Any],
) -> dict[str, Any]:
    hint_map = {hint.get("role"): hint for hint in target_profile.get("free_use_hints", []) if isinstance(hint, dict)}
    free_function = hint_map.get("free", {}).get("function")
    use_function = hint_map.get("use", {}).get("function")
    focus_file = hint_map.get("free", {}).get("file") or hint_map.get("use", {}).get("file")
    frames = set(candidate_match.get("crash_frames", []))
    files = set(candidate_match.get("crash_files", []))
    specific_free_hit = bool(free_function and free_function in frames)
    specific_use_hit = bool(use_function and use_function in frames)
    specific_file_hit = bool(focus_file and focus_file in files)
    net_enrichment = candidate_match.get("net_enrichment", {})
    specific_alignment = (
        candidate_match.get("uaf_type_match", False)
        and specific_free_hit
        and specific_use_hit
        and bool(net_enrichment.get("has_teardown_use_pair", False))
    )
    return {
        "path_relevant": bool(net_enrichment.get("is_net_crash", False)),
        "subsystem_relevance_score": round(float(net_enrichment.get("subsystem_relevance_score", 0.0) or 0.0), 3),
        "specific_free_function": free_function,
        "specific_use_function": use_function,
        "specific_free_hit": specific_free_hit,
        "specific_use_hit": specific_use_hit,
        "specific_file_hit": specific_file_hit,
        "free_use_hint_match": bool(candidate_match.get("free_use_hint_match", False)),
        "uaf_type_match": bool(candidate_match.get("uaf_type_match", False)),
        "match_score": round(float(candidate_match.get("match_score", 0.0) or 0.0), 3),
        "specific_candidate_alignment": specific_alignment,
        "alignment_quality": "specific"
        if specific_alignment
        else "subsystem"
        if net_enrichment.get("is_net_crash", False)
        else "unrelated",
    }


def classify_reproducibility(
    *,
    attempts: int,
    crash_count: int,
) -> dict[str, Any]:
    rate = (crash_count / attempts) if attempts else 0.0
    if attempts == 0:
        label = "not-attempted"
    elif crash_count >= 2:
        label = "reproducible crash"
    elif crash_count == 1:
        label = "unstable crash"
    else:
        label = "one-off crash"
    return {
        "attempts": attempts,
        "crash_count": crash_count,
        "repro_rate": round(rate, 3),
        "classification": label,
    }


def classify_net_runtime_verdict(
    *,
    preflight_ready: bool,
    execution_evidence_summary: dict[str, Any],
    crash_evidence_summary: dict[str, Any],
    candidate_evidence_summary: dict[str, Any],
    reproducibility_summary: dict[str, Any],
    known_bug_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    known_bug_review = known_bug_review or {"status": "unchecked"}
    reasons: list[str] = []

    if not preflight_ready:
        reasons.append("Strict live preflight did not pass, so no runtime result is trustworthy.")
        verdict = "environment/setup failure"
    elif not execution_evidence_summary.get("target_family_hit") or execution_evidence_summary.get("phase_reached") == "unknown":
        reasons.append("Execution did not reach the NETLINK_NETFILTER target family in a meaningful way.")
        verdict = "target not reached"
    elif not crash_evidence_summary.get("crash_detected"):
        reasons.append("Trigger path was exercised without a kernel crash signal.")
        verdict = "target reached, no crash"
    elif not candidate_evidence_summary.get("path_relevant"):
        reasons.append("Observed crash is not netfilter/nf_tables relevant.")
        verdict = "unrelated crash"
    else:
        reasons.append("Crash is netfilter relevant and happened after target execution.")
        has_real_crash = crash_evidence_summary.get("real_crash_signal")
        reproducible = reproducibility_summary.get("crash_count", 0) >= 2
        prefix_ok = execution_evidence_summary.get("prefix_preserved")
        trigger_ok = execution_evidence_summary.get("trigger_phase_reached")
        candidate_specific = candidate_evidence_summary.get("specific_candidate_alignment")
        passes_bug_bar = all([has_real_crash, reproducible, prefix_ok, trigger_ok, candidate_specific])
        if passes_bug_bar:
            reasons.append("Real-crash bar passed: real crash, reproduced at least twice, target path preserved, candidate alignment is specific.")
            review_status = known_bug_review.get("status", "unchecked")
            if review_status in {"known_duplicate", "likely_duplicate", "fixed_upstream"}:
                reasons.append("Manual known-bug review marked this signature as likely duplicate/fixed.")
                verdict = "known/likely-duplicate crash candidate"
            elif review_status == "checked-novel":
                reasons.append("Manual known-bug review completed without duplicate indicators.")
                verdict = "reproducible kernel bug candidate"
            else:
                reasons.append("Known-bug hygiene has not been completed yet.")
                verdict = "novelty-unchecked bug candidate"
        else:
            reasons.append("Crash correlation exists, but the real-crash bar for a validated bug candidate was not met.")
            verdict = "candidate-correlated live crash"

    return {
        "verdict_class": verdict,
        "reasons": reasons,
        "real_crash_bar": {
            "real_crash_signal": bool(crash_evidence_summary.get("real_crash_signal")),
            "reproduced_at_least_twice": reproducibility_summary.get("crash_count", 0) >= 2,
            "nf_tables_relevant": bool(candidate_evidence_summary.get("path_relevant")),
            "prefix_and_lifecycle_preserved": bool(execution_evidence_summary.get("prefix_preserved") and execution_evidence_summary.get("trigger_phase_reached")),
            "specific_candidate_alignment": bool(candidate_evidence_summary.get("specific_candidate_alignment")),
        },
        "signals": {
            "preflight_ready": preflight_ready,
            "phase_reached": execution_evidence_summary.get("phase_reached"),
            "crash_kind": crash_evidence_summary.get("crash_kind"),
            "match_score": candidate_evidence_summary.get("match_score"),
            "repro_classification": reproducibility_summary.get("classification"),
            "known_bug_review_status": known_bug_review.get("status", "unchecked"),
        },
    }


def classify_net_lab_state(
    *,
    runtime_verdict: dict[str, Any],
    exact_source_frames: bool,
    lab_only: bool,
) -> dict[str, Any]:
    runtime_class = runtime_verdict.get("verdict_class")
    bug_bar = runtime_verdict.get("real_crash_bar", {})
    reasons: list[str] = []

    if all(
        [
            bug_bar.get("real_crash_signal"),
            bug_bar.get("reproduced_at_least_twice"),
            bug_bar.get("nf_tables_relevant"),
            bug_bar.get("prefix_and_lifecycle_preserved"),
            bug_bar.get("specific_candidate_alignment"),
            exact_source_frames,
        ]
    ):
        if lab_only:
            verdict = "patch candidate for reproduced lab bug"
            reasons.append("Strict runtime proof passed with exact expected source frames in the lab-only target.")
        else:
            verdict = "confirmed lab bug"
            reasons.append("Strict runtime proof passed with exact expected source frames.")
    elif runtime_class in {"candidate-correlated live crash", "unrelated crash"}:
        verdict = "candidate-correlated crash"
        reasons.append("Crash evidence exists, but the strict runtime proof bar was not met.")
    else:
        verdict = "no bug confirmed; exact blocker"
        reasons.append("Runtime proof did not yield a confirmed lab bug.")

    return {
        "lab_state": verdict,
        "reasons": reasons,
        "runtime_verdict_class": runtime_class,
        "exact_source_frames": exact_source_frames,
    }
