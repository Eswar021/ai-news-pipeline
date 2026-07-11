from __future__ import annotations

from copy import deepcopy
from typing import Any


def retime_visual_plan_result(result: dict[str, Any], target_duration_seconds: float) -> dict[str, Any]:
    """Scale a validated scene plan to an already-generated audio duration."""
    target = float(target_duration_seconds)
    if target <= 0:
        raise ValueError("target_duration_seconds must be positive")

    updated = deepcopy(result)
    plan = updated.get("data", {}).get("visual_scene_plan", {})
    scenes = plan.get("scene_timeline")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("visual_scene_plan.scene_timeline is missing or empty")
    original = float(scenes[-1].get("end_seconds", 0) or 0)
    if original <= 0:
        raise ValueError("visual scene timeline has no positive end time")
    scale = target / original

    _scale_ranges(scenes, scale)
    _scale_ranges(plan.get("story_sections", []), scale)
    _scale_ranges(plan.get("visual_beat_map", []), scale)
    _scale_relative_ranges(plan.get("visual_beat_map", []), scale)
    _scale_audio_timeline(plan.get("audio_timeline", {}), scale, target)

    coverage = plan.setdefault("coverage", {})
    max_scene_duration = max(float(scene["duration_seconds"]) for scene in scenes)
    configured_cap = (plan.get("scene_policy") or {}).get("max_scene_seconds")
    if configured_cap is not None and max_scene_duration > float(configured_cap) + 0.01:
        raise ValueError(
            f"Retimed scene duration {max_scene_duration:.2f}s exceeds configured cap {float(configured_cap):.2f}s"
        )
    coverage.update(
        {
            "total_duration_seconds": round(target, 2),
            "covered_duration_seconds": round(target, 2),
            "uncovered_duration_seconds": 0.0,
            "gap_count": 0,
            "overlap_count": 0,
            "max_scene_duration_seconds": max_scene_duration,
        }
    )
    warnings = plan.setdefault("planner_warnings", [])
    warnings.append(
        f"Timeline retimed from {original:.2f}s to {target:.2f}s for the selected voiceover (scale={scale:.5f})."
    )
    checks = plan.setdefault("checks", {"passed": True, "errors": [], "warnings": []})
    checks.setdefault("warnings", []).append(warnings[-1])

    summary = updated.setdefault("summary", {})
    summary["voiceover_duration_seconds"] = round(target, 2)
    summary["max_scene_duration_seconds"] = coverage["max_scene_duration_seconds"]
    summary["retimed_to_voiceover"] = True
    summary["retime_scale"] = round(scale, 6)
    return updated


def _scale_ranges(items: Any, scale: float) -> None:
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("start_seconds"), (int, float)):
            item["start_seconds"] = round(float(item["start_seconds"]) * scale, 2)
        if isinstance(item.get("end_seconds"), (int, float)):
            item["end_seconds"] = round(float(item["end_seconds"]) * scale, 2)
        if "start_seconds" in item and "end_seconds" in item:
            item["duration_seconds"] = round(float(item["end_seconds"]) - float(item["start_seconds"]), 2)


def _scale_relative_ranges(items: Any, scale: float) -> None:
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in ("relative_start_seconds", "relative_end_seconds"):
            if isinstance(item.get(key), (int, float)):
                item[key] = round(float(item[key]) * scale, 2)


def _scale_audio_timeline(audio_timeline: Any, scale: float, target: float) -> None:
    if not isinstance(audio_timeline, dict):
        return
    audio_timeline["duration_seconds"] = round(target, 2)
    _scale_ranges(audio_timeline.get("chunks", []), scale)
