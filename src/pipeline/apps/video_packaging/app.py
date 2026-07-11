from __future__ import annotations

from datetime import datetime, timedelta, timezone
from .config import KNOWN_FUTURE_FORMATS, SCRIPT_APP_BY_FORMAT, SUPPORTED_FORMATS
from .contract import VideoPackagingRequest, VideoPackagingResponse
from .formats.roundup import build_roundup_packet


IST = timezone(timedelta(hours=5, minutes=30))


def run(input_json: dict) -> dict:
    request = VideoPackagingRequest.model_validate(input_json)
    run_id = request.run.run_id
    target_format = request.config.target_format

    if target_format not in SUPPORTED_FORMATS:
        if target_format in KNOWN_FUTURE_FORMATS:
            raise NotImplementedError(
                f"video_packaging target_format '{target_format}' is not implemented yet. "
                "Only 'roundup' is active in the current app."
            )
        raise ValueError(f"Unsupported target_format: {target_format}")

    stories = request.input.story_mapping.data.stories
    generated_at = _iso_now()
    roundup_cfg = request.config.roundup.model_dump(mode="json")
    built = build_roundup_packet(stories, roundup_cfg)
    packet = built["packet"]
    selection_stats = built["selection_stats"]
    selected_count = int(selection_stats["selected_story_count"])
    min_stories = int(roundup_cfg["min_stories"])
    status = "ok" if selected_count >= min_stories else "failed"
    failure_reason = "" if status == "ok" else (
        f"Only {selected_count} story/stories qualified; at least {min_stories} are required for a roundup."
    )

    response = VideoPackagingResponse(
        status=status,
        data={
            "run_id": run_id,
            "generated_at": generated_at,
            "selected_format": target_format,
            "script_app": SCRIPT_APP_BY_FORMAT[target_format],
            "video_packet": packet,
        },
        summary={
            "input_story_count": int(selection_stats["input_story_count"]),
            "candidate_story_count": int(selection_stats["candidate_story_count"]),
            "selected_story_count": selected_count,
            "rejected_story_count": int(selection_stats["rejected_story_count"]),
            "selection_reason_counts": selection_stats["selection_reason_counts"],
            "role_counts": built["role_counts"],
            "target_duration_seconds": int(roundup_cfg["target_duration_seconds"]),
            "failure_reason": failure_reason,
            "selected_story_ids": selection_stats["selected_story_ids"],
            "rejected_story_ids": selection_stats["rejected_story_ids"],
        },
        handoff={
            "ready_for_script_generation": status == "ok",
            "script_app": SCRIPT_APP_BY_FORMAT[target_format],
            "selected_format": target_format,
        },
    )
    return response.model_dump(mode="json")


def _iso_now() -> str:
    return datetime.now(IST).isoformat()
