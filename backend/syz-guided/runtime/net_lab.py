#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import pathlib
from typing import Any

from triage.net_verdict import classify_net_lab_state as _classify_net_lab_state


def _sha256(path: pathlib.Path | None) -> str | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def build_kernel_provenance(
    *,
    kernel: pathlib.Path,
    disk_image: pathlib.Path,
    preflight_environment: dict[str, Any],
    proof_kernel_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        'kernel_image_path': str(kernel),
        'kernel_image_sha256': _sha256(kernel),
        'kernel_image_size_bytes': kernel.stat().st_size if kernel.exists() else None,
        'disk_image_path': str(disk_image),
        'disk_image_sha256': _sha256(disk_image),
        'disk_image_size_bytes': disk_image.stat().st_size if disk_image.exists() else None,
        'kernel_config_path': preflight_environment.get('kernel_config_path'),
        'kernel_config_present': preflight_environment.get('kernel_config_present', []),
        'kernel_config_missing': preflight_environment.get('kernel_config_missing', []),
        'proof_kernel_meta': proof_kernel_meta,
    }


def build_source_frame_summary(
    *,
    crash_evidence_summary: dict[str, Any],
    candidate_evidence_summary: dict[str, Any],
    target_profile: dict[str, Any],
    reproducibility_summary: dict[str, Any],
) -> dict[str, Any]:
    hint_map = {hint.get('role'): hint for hint in target_profile.get('free_use_hints', []) if isinstance(hint, dict)}
    expected_free = hint_map.get('free', {}).get('function')
    expected_use = hint_map.get('use', {}).get('function')
    top_frames = list(crash_evidence_summary.get('top_frames', []))
    source_files = list(crash_evidence_summary.get('source_files', []))
    return {
        'crash_title': crash_evidence_summary.get('title'),
        'crash_signature': crash_evidence_summary.get('signature'),
        'top_frames': top_frames,
        'source_files': source_files,
        'expected_free_frame': expected_free,
        'expected_use_frame': expected_use,
        'observed_expected_free_frame': bool(expected_free and expected_free in top_frames),
        'observed_expected_use_frame': bool(expected_use and expected_use in top_frames),
        'exact_expected_pair_observed': bool(
            expected_free and expected_free in top_frames and expected_use and expected_use in top_frames
        ),
        'specific_candidate_alignment': bool(candidate_evidence_summary.get('specific_candidate_alignment')),
        'path_relevant': bool(candidate_evidence_summary.get('path_relevant')),
        'repro_classification': reproducibility_summary.get('classification'),
    }


def classify_lab_net_state(
    *,
    runtime_verdict: dict[str, Any],
    source_frame_summary: dict[str, Any],
    reproducibility_summary: dict[str, Any],
    lab_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lab_context = lab_context or {}
    summary = _classify_net_lab_state(
        runtime_verdict=runtime_verdict,
        exact_source_frames=bool(source_frame_summary.get('exact_expected_pair_observed')),
        lab_only=bool(lab_context.get('lab_only', False)),
    )
    summary['reproducibility'] = reproducibility_summary.get('classification')
    return summary


def _append_reason(score_reasons: list[str], reason: str) -> None:
    if reason not in score_reasons:
        score_reasons.append(reason)


def rank_net_files(
    *,
    candidate: dict[str, Any] | None,
    target_profile: dict[str, Any],
    manifest: dict[str, Any] | None = None,
    source_frame_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = manifest or {}
    source_frame_summary = source_frame_summary or {}
    rows: dict[str, dict[str, Any]] = {}

    def ensure(path: str) -> dict[str, Any]:
        row = rows.setdefault(path, {'path': path, 'score': 0.0, 'reasons': []})
        return row

    for path in target_profile.get('focus_files', []):
        if isinstance(path, str) and path:
            row = ensure(path)
            row['score'] += 0.5
            _append_reason(row['reasons'], 'target profile focus file')

    for hint in target_profile.get('free_use_hints', []):
        if not isinstance(hint, dict):
            continue
        path = hint.get('file')
        if isinstance(path, str) and path:
            row = ensure(path)
            row['score'] += 0.35
            _append_reason(row['reasons'], f"{hint.get('role', 'unknown')} frame hint")

    for path in source_frame_summary.get('source_files', []):
        if isinstance(path, str) and path:
            row = ensure(path)
            row['score'] += 0.4
            _append_reason(row['reasons'], 'observed crash source file')

    for prefix in manifest.get('kernel_area_prefixes', []):
        if not isinstance(prefix, str):
            continue
        for path, row in rows.items():
            if path.startswith(prefix):
                row['score'] += 0.1
                _append_reason(row['reasons'], f'within manifest kernel area prefix {prefix}')

    ranked = sorted(
        ({**row, 'score': round(row['score'], 3)} for row in rows.values()),
        key=lambda row: (-row['score'], row['path']),
    )
    return {
        'ranked_files': ranked,
        'inputs': {
            'focus_files': target_profile.get('focus_files', []),
            'free_use_hints': target_profile.get('free_use_hints', []),
            'kernel_area_prefixes': manifest.get('kernel_area_prefixes', []),
            'source_files': source_frame_summary.get('source_files', []),
            'candidate_id': None if candidate is None else candidate.get('candidate_id'),
        },
    }


def rank_net_seeds(
    *,
    seed_manifest: dict[str, Any],
    target_profile: dict[str, Any],
    candidate: dict[str, Any] | None = None,
    proof_mode: str = 'off',
) -> dict[str, Any]:
    preferred = ['delete_dump', 'dump_delete', 'update_dump_delete', 'delete_close', 'dump_close']
    rows: list[dict[str, Any]] = []
    for seed in seed_manifest.get('seeds', []):
        if not isinstance(seed, dict):
            continue
        name = str(seed.get('name', ''))
        if not name:
            continue
        score = 0.0
        reasons: list[str] = []
        lower = name.lower()
        for index, token in enumerate(preferred):
            if token in lower:
                score += max(0.0, 1.0 - (index * 0.15))
                _append_reason(reasons, f'matches prioritized lifecycle variant {token}')
                break
        if 'dump' in lower:
            score += 0.25
            _append_reason(reasons, 'includes dump lifecycle phase')
        if 'delete' in lower:
            score += 0.25
            _append_reason(reasons, 'includes delete lifecycle phase')
        if proof_mode == 'controlled' and 'delete_dump' in lower:
            score += 0.5
            _append_reason(reasons, 'controlled proof mode prioritizes delete->dump trigger seed')
        call_count = seed.get('call_count')
        if isinstance(call_count, int):
            score += min(call_count, 8) / 100.0
            _append_reason(reasons, f'call count {call_count}')
        rows.append({
            'seed': name,
            'score': round(score, 3),
            'reasons': reasons,
            'call_count': call_count,
        })

    ranked = sorted(rows, key=lambda row: (-row['score'], row['seed']))
    return {
        'ranked_seeds': ranked,
        'inputs': {
            'candidate_id': None if candidate is None else candidate.get('candidate_id'),
            'proof_mode': proof_mode,
            'focus_files': target_profile.get('focus_files', []),
            'free_use_hints': target_profile.get('free_use_hints', []),
        },
    }


def build_blocker_report(
    *,
    runtime_verdict: dict[str, Any],
    single_seed_result: dict[str, Any] | None,
    preflight_summary_path: pathlib.Path,
    seed_dir: pathlib.Path | None,
) -> dict[str, Any] | None:
    verdict_class = runtime_verdict.get('verdict_class')
    single_seed_result = single_seed_result or {}
    if verdict_class in {'reproducible kernel bug candidate', 'novelty-unchecked bug candidate', 'known/likely-duplicate crash candidate'}:
        return None

    classification = single_seed_result.get('classification')
    if verdict_class == 'environment/setup failure':
        return {
            'stage': 'preflight',
            'failure_class': 'environment/setup failure',
            'reason': 'Strict live preflight did not pass.',
            'primary_artifact': str(preflight_summary_path),
            'recommended_next_step': 'Inspect failing host/guest checks in preflight_summary.json and repair the first failing prerequisite.',
        }

    primary_artifact = str(seed_dir / 'seed_execution_status.json') if seed_dir else str(preflight_summary_path)
    reason_map = {
        'guest-exec-failure': 'Guest command failed before a classified runtime result could be observed.',
        'stalled': 'Seed execution exceeded the timeout without observable progress.',
        'timed-out': 'Seed execution timed out after partial progress.',
        'target-not-reached': 'Seed completed without meaningfully reaching the NETLINK_NETFILTER target path.',
        'completed-no-crash': 'Seed completed without a real kernel crash signal.',
        'completed-crash': 'Crash observed, but the strict proof bar or relevance requirements were not met.',
    }
    next_step_map = {
        'guest-exec-failure': 'Inspect syz-execprog stdout/stderr and the saved seed to fix the guest execution handoff.',
        'stalled': 'Inspect the saved console, dmesg, and seed execution status to distinguish a slow path from a dead run.',
        'timed-out': 'Increase the bounded runtime or reduce the seed to a smaller reproducer candidate.',
        'target-not-reached': 'Inspect the ranking decision and seed lifecycle order, then adjust toward the intended trigger path.',
        'completed-no-crash': 'Inspect triage and source-frame summaries, then move to the next bounded stage or patch the lab target.',
        'completed-crash': 'Inspect crash evidence, source frames, and manual known-bug review before escalating the result.',
    }
    return {
        'stage': 'single-seed-validation',
        'failure_class': classification or verdict_class,
        'reason': reason_map.get(classification, runtime_verdict.get('reasons', ['Runtime proof did not yield a confirmed bug.'])[0]),
        'primary_artifact': primary_artifact,
        'recommended_next_step': next_step_map.get(classification, 'Inspect the saved runtime artifacts and advance from the first failing stage only.'),
    }


def build_lab_run_bundle(
    *,
    kernel_provenance: dict[str, Any],
    source_frame_summary: dict[str, Any],
    runtime_verdict: dict[str, Any],
    lab_state: dict[str, Any],
    blocker_report: dict[str, Any] | None,
    guest_environment_summary: dict[str, Any],
    single_seed_result: dict[str, Any] | None,
    seed_dir: pathlib.Path | None,
    out_dir: pathlib.Path,
) -> dict[str, Any]:
    seed_dir_str = None if seed_dir is None else str(seed_dir)
    triage_path = None if seed_dir is None else str(seed_dir / 'triage_report_v1.json')
    dmesg_path = None if seed_dir is None else str(seed_dir / 'guest.dmesg.txt')
    console_path = None if seed_dir is None else str(seed_dir / 'console.log')
    minimization_handoff = out_dir / 'repro'
    return {
        'kernel_provenance': kernel_provenance,
        'guest_environment_summary': guest_environment_summary,
        'seed_dir': seed_dir_str,
        'seed_path': None if seed_dir is None else str(seed_dir / (single_seed_result or {}).get('seed', '')),
        'guest_tool_paths': {
            'syz_execprog': guest_environment_summary.get('guest_syz_execprog_path'),
            'syz_executor': guest_environment_summary.get('guest_syz_executor_path'),
        },
        'boot_console_log': console_path,
        'guest_dmesg_log': dmesg_path,
        'triage_report': triage_path,
        'source_frame_summary': source_frame_summary,
        'runtime_verdict': runtime_verdict,
        'lab_state': lab_state,
        'single_seed_result': single_seed_result,
        'blocker_report': blocker_report,
        'minimization_handoff_root': str(minimization_handoff),
    }
