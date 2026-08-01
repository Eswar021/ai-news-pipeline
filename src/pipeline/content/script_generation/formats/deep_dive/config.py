from __future__ import annotations

SCRIPT_APP = "script_generation.formats.deep_dive"
SUPPORTED_FORMAT = "deep_dive"

DIRECTOR_PROMPT_MODULE = "deep_dive_director"
SOURCE_RESEARCHER_PROMPT_MODULE = "deep_dive_source_researcher"
SECTION_WRITER_PROMPT_MODULE = "deep_dive_section_writer"
SECTION_REVIEWER_PROMPT_MODULE = "deep_dive_section_reviewer"
BOOKEND_WRITER_PROMPT_MODULE = "deep_dive_bookend_writer"
BOOKEND_REVIEWER_PROMPT_MODULE = "deep_dive_bookend_reviewer"

# deep_dive reuses the shared LLM role keys for config routing: the section
# writer/reviewer map to the story_writer/story_reviewer roles.
SCRIPT_LLM_ROLES = (
    "source_researcher",
    "director",
    "story_writer",
    "story_reviewer",
    "bookend_writer",
    "bookend_reviewer",
)

DEFAULT_MIN_ANGLE_SECTIONS = 3
DEFAULT_MAX_ANGLE_SECTIONS = 6
