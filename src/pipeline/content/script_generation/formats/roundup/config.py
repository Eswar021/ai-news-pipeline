from __future__ import annotations

SCRIPT_APP = "script_generation.formats.roundup"
SUPPORTED_FORMAT = "roundup"
DIRECTOR_PROMPT_MODULE = "roundup_director"
SOURCE_RESEARCHER_PROMPT_MODULE = "roundup_source_researcher"
STORY_WRITER_PROMPT_MODULE = "roundup_story_writer"
STORY_REVIEWER_PROMPT_MODULE = "roundup_story_reviewer"
BOOKEND_WRITER_PROMPT_MODULE = "roundup_bookend_writer"
BOOKEND_REVIEWER_PROMPT_MODULE = "roundup_bookend_reviewer"

SCRIPT_LLM_ROLES = (
    "source_researcher",
    "director",
    "story_writer",
    "story_reviewer",
    "bookend_writer",
    "bookend_reviewer",
)

DEFAULT_SCRIPT_WORKER_COUNT = 1
DEFAULT_DIAGNOSTIC_WORDS_PER_MINUTE = 140
DEFAULT_LLM_RETRY_ENABLED = True
DEFAULT_LLM_RETRY_MAX_ATTEMPTS = 5
DEFAULT_LLM_RETRY_MAX_STRUCTURED_OUTPUT_ATTEMPTS = 2
DEFAULT_LLM_REQUEST_TIMEOUT_SECONDS = 300.0
DEFAULT_LLM_RETRY_INITIAL_DELAY_SECONDS = 1.0
DEFAULT_LLM_RETRY_MAX_DELAY_SECONDS = 30.0
DEFAULT_REVIEW_ENABLED = True
DEFAULT_MAX_REVISION_PASSES = 1
DEFAULT_TITLE_CARD_SECONDS = 2.8
DEFAULT_MAX_STORY_CONTEXT_CHARS = 500_000
DEFAULT_MAX_EPISODE_CONTEXT_CHARS = 1_500_000

BEAT_TYPES = (
    "hook",
    "transition",
    "what_changed",
    "explanation",
    "example",
    "why_it_matters",
    "caveat",
    "takeaway",
    "intro",
    "conclusion",
)

VISUAL_INTENTS = (
    "story_title",
    "source_proof",
    "entity_intro",
    "product_demo",
    "metric_explainer",
    "process_explainer",
    "comparison",
    "context_media",
    "transition",
    "takeaway",
)
