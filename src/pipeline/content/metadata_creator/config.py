from __future__ import annotations


SUPPORTED_FORMAT = "roundup"
# Metadata generation (titles/tags/description/chapters) is format-agnostic; only
# the title-framing prompt differs per format, so each supported format maps to
# its own prompt module while sharing all the surrounding machinery.
SUPPORTED_FORMATS = ("roundup", "deep_dive")
PACKAGE_TYPE = "youtube_metadata_package"
METADATA_PROMPT_MODULE = "youtube_metadata_creator"
METADATA_PROMPT_MODULE_BY_FORMAT = {
    "roundup": "youtube_metadata_creator",
    "deep_dive": "youtube_metadata_creator_deep_dive",
}

DEFAULT_TITLE_OPTION_COUNT = 8
DEFAULT_THUMBNAIL_TEXT_OPTION_COUNT = 5
DEFAULT_MAX_TAGS = 20

ACRONYM_TAGS = {
    "ai": "AI",
    "api": "API",
    "arxiv": "arXiv",
    "aws": "AWS",
    "cs": "CS",
    "fm-cgm": "FM-CGM",
    "gpt": "GPT",
    "hipaa": "HIPAA",
    "llm": "LLM",
    "mcp": "MCP",
    "nvidia": "NVIDIA",
    "openai": "OpenAI",
}

BLOCKED_TAG_VALUES = {
    "unknown",
    "none",
    "null",
    "n/a",
    "ai company blogs",
    "tech news apis",
    "research papers",
    "youtube podcast transcripts",
    "community signals",
    "official update",
    "industry news",
    "research result",
}
