"""
Layer 9 — Repetition Safety Checker

Checks the current script/package against published-memory records to catch
recycled titles, repeated story coverage, and framing fatigue that slipped
past Layer 5 novelty selection.

This is intentionally post-script and post-metadata-draft: it evaluates the
actual title direction and selected story set that the viewer would see.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

from config.paths import MEMORY_DIR


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _normalize_title(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _title_similarity(a: str, b: str) -> float:
    na = _normalize_title(a)
    nb = _normalize_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _published_video_map(video_records: list[dict]) -> dict[str, dict]:
    published = {}
    for rec in video_records:
        published_at = rec.get("timestamps", {}).get("published_at")
        if published_at:
            published[rec.get("video_id", "")] = rec
    return published


def _current_title(ctx: dict) -> str:
    title = ctx.get("youtube_metadata", {}).get("recommended_title", "")
    if title:
        return title

    ttp = ctx.get("title_thumbnail", {})
    for option in ttp.get("recommended_title_angles", []):
        if option.get("accuracy_risk") == "low" and option.get("title"):
            return option["title"]
    for option in ttp.get("recommended_title_angles", []):
        if option.get("title"):
            return option["title"]
    return ""


def check(ctx: dict, memory_dir: Path = MEMORY_DIR) -> dict:
    video_records = _load_jsonl(memory_dir / "video_memory.jsonl")
    editorial_records = _load_jsonl(memory_dir / "editorial_pattern_memory.jsonl")

    published_videos = _published_video_map(video_records)
    published_video_ids = set(published_videos.keys())
    published_editorials = [
        rec for rec in editorial_records
        if rec.get("video_id", "") in published_video_ids
    ]

    current_title = _current_title(ctx)
    current_hook_type = (
        ctx.get("script_writer_brief", {})
        .get("hook_instruction", {})
        .get("hook_type", "")
    )
    current_story_ids = set(
        ctx.get("script_writer_brief", {})
        .get("video_identity", {})
        .get("selected_story_ids", [])
    )
    primary_story_id = (
        ctx.get("script_writer_brief", {})
        .get("video_identity", {})
        .get("primary_story_id")
    )
    if primary_story_id:
        current_story_ids.add(primary_story_id)

    issues = []
    warnings = []

    # Story reuse against published history
    for video_id, rec in published_videos.items():
        prior_story_ids = set(rec.get("coverage", {}).get("story_ids", []))
        overlap = sorted(current_story_ids & prior_story_ids)
        if not overlap:
            continue
        for story_id in overlap:
            issues.append({
                "repetition_type": "story_reuse",
                "severity": "medium",
                "message": f"Story {story_id} was already covered in published video {video_id}.",
                "story_id": story_id,
                "matched_video_id": video_id,
                "matched_published_video_id": rec.get("publishing", {}).get("youtube_video_id", ""),
                "published_at": rec.get("timestamps", {}).get("published_at", ""),
            })

    # Title reuse / near-reuse
    if current_title:
        current_norm = _normalize_title(current_title)
        seen_pairs = set()
        for rec in published_editorials:
            video_id = rec.get("video_id", "")
            title_candidates = []

            working_title = rec.get("titles", {}).get("working_title", "")
            if working_title:
                title_candidates.append(("working_title", working_title))

            for option in rec.get("titles", {}).get("approved_title_angles", []):
                title = option.get("title", "")
                if title:
                    title_candidates.append(("approved_title", title))

            for blocked in rec.get("titles", {}).get("blocked_title_angles", []):
                if blocked:
                    title_candidates.append(("blocked_title_angle", blocked))

            best_match = None
            for match_type, prior_title in title_candidates:
                pair_key = (video_id, prior_title)
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                prior_norm = _normalize_title(prior_title)
                if not prior_norm:
                    continue
                similarity = _title_similarity(current_title, prior_title)
                exact = current_norm == prior_norm

                if exact:
                    severity = "high" if match_type != "blocked_title_angle" else "medium"
                elif similarity >= 0.90:
                    severity = "medium"
                else:
                    continue

                candidate = {
                    "repetition_type": "title_reuse",
                    "severity": severity,
                    "message": (
                        f"Current title is very close to a previously published title from {video_id}."
                        if match_type != "blocked_title_angle"
                        else f"Current title is close to a previously blocked title angle from {video_id}."
                    ),
                    "current_title": current_title,
                    "matched_title": prior_title,
                    "matched_title_type": match_type,
                    "matched_video_id": video_id,
                    "matched_published_video_id": published_videos.get(video_id, {}).get("publishing", {}).get("youtube_video_id", ""),
                    "published_at": published_videos.get(video_id, {}).get("timestamps", {}).get("published_at", ""),
                    "similarity": round(similarity, 3),
                }
                if best_match is None or candidate["severity"] == "high":
                    best_match = candidate
                if exact:
                    break

            if best_match:
                issues.append(best_match)

    # Hook fatigue warning from recent published history
    if current_hook_type:
        recent_hook_types = [
            rec.get("hook", {}).get("hook_type", "")
            for rec in published_editorials[-5:]
            if rec.get("hook", {}).get("hook_type")
        ]
        repeat_count = sum(1 for hook_type in recent_hook_types if hook_type == current_hook_type)
        if repeat_count >= 3:
            warnings.append(
                f"Hook type '{current_hook_type}' appears in {repeat_count} of the last "
                f"{len(recent_hook_types)} published editorial patterns."
            )

    high_count = sum(1 for issue in issues if issue["severity"] == "high")
    medium_count = sum(1 for issue in issues if issue["severity"] == "medium")
    status = "passed"
    if high_count:
        status = "failed"
    elif medium_count or warnings:
        status = "passed_with_warnings"

    return {
        "status": status,
        "passed": high_count == 0,
        "checked_against_published_videos": len(published_videos),
        "current_title": current_title,
        "current_hook_type": current_hook_type,
        "story_ids_checked": sorted(current_story_ids),
        "high_count": high_count,
        "medium_count": medium_count,
        "issue_count": len(issues),
        "issues": issues,
        "warnings": warnings,
    }

