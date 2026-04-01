"""Match a parsed crash against a candidate's target profile.

Scoring:
  - focus_frame_hit:     any crash stack frame matches focus_frames
  - focus_file_hit:      any crash source file matches focus_files
  - free_use_hint_match: crash function matches loc0/loc1 function names
  - uaf_type_match:      KASAN type is 'use-after-free'
  - match_score:         weighted combination (0.0–1.0)
"""

from __future__ import annotations

from typing import Any


def match_crash(crash: dict, target_profile: dict) -> dict:
    """Score how well a parsed crash matches the candidate target profile.

    Args:
        crash: output of parse_kasan.parse_kasan_report()
        target_profile: target_profile.json contents

    Returns:
        dict with boolean hit flags and overall match_score
    """
    focus_frames = set(target_profile.get("focus_frames", []))
    focus_files = set(target_profile.get("focus_files", []))
    crash_frames = set(crash.get("stack_frames", []))
    crash_files = set(crash.get("source_files", []))

    # Free/use hint function names.
    hint_funcs = set()
    for hint in target_profile.get("free_use_hints", []):
        fn = hint.get("function")
        if fn:
            hint_funcs.add(fn)

    focus_frame_hit = bool(focus_frames & crash_frames)
    focus_file_hit = bool(focus_files & crash_files)
    free_use_hint_match = bool(hint_funcs & crash_frames)
    uaf_type_match = crash.get("type", "").lower() in ("use-after-free", "slab-use-after-free")

    # Weighted score.
    score = 0.0
    if uaf_type_match:
        score += 0.30
    if focus_frame_hit:
        score += 0.30
    if free_use_hint_match:
        score += 0.25
    if focus_file_hit:
        score += 0.15

    return {
        "focus_frame_hit": focus_frame_hit,
        "focus_file_hit": focus_file_hit,
        "free_use_hint_match": free_use_hint_match,
        "uaf_type_match": uaf_type_match,
        "match_score": min(score, 1.0),
    }
