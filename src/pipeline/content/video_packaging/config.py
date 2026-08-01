from __future__ import annotations

SCRIPT_APP_BY_FORMAT = {
    "roundup": "script_generation.formats.roundup",
    "deep_dive": "script_generation.formats.deep_dive",
}

ROUNDUP_FORMAT_CONTRACT = {
    "format": "roundup",
    "script_app": SCRIPT_APP_BY_FORMAT["roundup"],
    "section_sequence": ["intro", "story_segments", "closing"],
    "allowed_segment_roles": ["lead", "major", "brief"],
    "must_use_selected_stories_only": True,
    "story_payload": "full_selected_stories_with_video_segment_metadata",
    "duration_mode": "content_driven",
    "timing_source_of_truth": "voiceover",
    "tone_control_owner": "script_generation",
}

DEEP_DIVE_FORMAT_CONTRACT = {
    "format": "deep_dive",
    "script_app": SCRIPT_APP_BY_FORMAT["deep_dive"],
    "section_sequence": ["intro", "angle_sections", "closing"],
    # The script director reads the one story and plans its angle sections; the
    # packet only carries the single chosen story with its complete records.
    "angle_planning": "llm_director_plans_angle_sections",
    "must_use_selected_stories_only": True,
    "story_payload": "single_story_full_records",
    "duration_mode": "content_driven",
    "timing_source_of_truth": "voiceover",
    "tone_control_owner": "script_generation",
}

FORMAT_CONTRACT_BY_FORMAT = {
    "roundup": ROUNDUP_FORMAT_CONTRACT,
    "deep_dive": DEEP_DIVE_FORMAT_CONTRACT,
}

SUPPORTED_FORMATS = {"roundup", "deep_dive"}
KNOWN_FUTURE_FORMATS = {"auto", "short"}
