from __future__ import annotations

# Default knobs are shared across formats.
from ...shared.defaults import (  # noqa: F401
    DEFAULT_DIAGNOSTIC_WORDS_PER_MINUTE,
    DEFAULT_LLM_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_LLM_RETRY_ENABLED,
    DEFAULT_LLM_RETRY_INITIAL_DELAY_SECONDS,
    DEFAULT_LLM_RETRY_MAX_ATTEMPTS,
    DEFAULT_LLM_RETRY_MAX_DELAY_SECONDS,
    DEFAULT_LLM_RETRY_MAX_STRUCTURED_OUTPUT_ATTEMPTS,
    DEFAULT_MAX_EPISODE_CONTEXT_CHARS,
    DEFAULT_MAX_REVISION_PASSES,
    DEFAULT_MAX_STORY_CONTEXT_CHARS,
    DEFAULT_REVIEW_ENABLED,
    DEFAULT_SCRIPT_WORKER_COUNT,
    DEFAULT_TITLE_CARD_SECONDS,
)

SCRIPT_APP = "script_generation.formats.deep_dive"
SUPPORTED_FORMAT = "deep_dive"

DIRECTOR_PROMPT_MODULE = "deep_dive_director"
SOURCE_RESEARCHER_PROMPT_MODULE = "deep_dive_source_researcher"
SECTION_WRITER_PROMPT_MODULE = "deep_dive_section_writer"
SECTION_REVIEWER_PROMPT_MODULE = "deep_dive_section_reviewer"
BOOKEND_WRITER_PROMPT_MODULE = "deep_dive_bookend_writer"
BOOKEND_REVIEWER_PROMPT_MODULE = "deep_dive_bookend_reviewer"

# LLM roles for this format (config `llm_roles` may override each).
SCRIPT_LLM_ROLES = (
    "source_researcher",
    "director",
    "section_writer",
    "section_reviewer",
    "bookend_writer",
    "bookend_reviewer",
)

# Deep-dive shape guardrails (config-overridable via DeepDiveScriptConfig).
DEFAULT_MIN_ANGLE_SECTIONS = 3
DEFAULT_MAX_ANGLE_SECTIONS = 6
