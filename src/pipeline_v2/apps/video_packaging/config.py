from __future__ import annotations

SCRIPT_APP_BY_FORMAT = {
    "roundup": "script_generation.formats.roundup",
}

ROUNDUP_FORMAT_CONTRACT = {
    "format": "roundup",
    "script_app": SCRIPT_APP_BY_FORMAT["roundup"],
    "section_sequence": ["intro", "story_segments", "closing"],
    "allowed_segment_roles": ["lead", "major", "brief"],
    "must_use_selected_stories_only": True,
    "story_payload": "full_selected_stories_with_video_segment_metadata",
    "tone_control_owner": "script_generation",
}

SUPPORTED_FORMATS = {"roundup"}
KNOWN_FUTURE_FORMATS = {"auto", "deep_dive"}
