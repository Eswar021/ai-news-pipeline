from __future__ import annotations

SCRIPT_APP = "script_generation.formats.roundup"
SUPPORTED_FORMAT = "roundup"
STORY_USAGE_PROMPT_MODULE = "story_usage_analyzer"
FULL_SCRIPT_PROMPT_MODULE = "roundup_full_script_writer"
REFLECTION_PROMPT_MODULE = "roundup_script_reflector"
REVISION_PROMPT_MODULE = "roundup_script_reviser"

DEFAULT_SCRIPT_WORKER_COUNT = 1
DEFAULT_REFLECTION_ENABLED = True
DEFAULT_MAX_REVISION_PASSES = 1
DEFAULT_REFLECTION_TARGET_SCORE = 8

VISUAL_DIRECTION_MARKERS = (
    "lower third",
    "on screen",
    "on-screen",
    "b-roll",
    "b roll",
    "overlay",
    "show on screen",
    "show this on screen",
    "show title card",
    "cut to",
    "visual note",
    "visual direction",
    "editor note",
)
