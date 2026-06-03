from __future__ import annotations

DEFAULT_SEMANTIC_PRIMARY_THRESHOLD = 0.80
DEFAULT_SEMANTIC_SUPPORTED_THRESHOLD = 0.78
DEFAULT_SEMANTIC_TITLE_ANCHOR_THRESHOLD = 0.74
DEFAULT_SEMANTIC_MERGE_GROUPS = [
    "ai_company_blogs",
    "tech_news_apis",
    "youtube_podcast_transcripts",
]

DEFAULT_STORY_LABEL_PROMPT_VERSION = "v1"
DEFAULT_STORY_LABEL_WORKER_COUNT = 10
DEFAULT_STORY_LABEL_TEMPERATURE = 0.15
DEFAULT_MAX_RECORDS_PER_STORY_LABEL = 6

VALID_ACTIONS = {
    "adopted",
    "disproved",
    "expanded",
    "launched",
    "updated",
    "partnered",
    "reported",
    "benchmarked",
    "researched",
    "funded",
    "criticized",
    "explained",
    "tutorial",
    "event_update",
    "unknown",
}

VALID_STORY_TYPES = {
    "official_update",
    "industry_news",
    "research_result",
    "community_product_launch",
    "community_repository",
    "tutorial_or_demo",
    "event_update",
    "reaction_or_opinion",
    "unknown",
}

VALID_EDITORIAL_VALUES = {"high", "medium", "low"}

VALID_TEMPORAL_RELATIONSHIPS = {
    "same_event",
    "follow_up",
    "broader_story_arc",
    "timeless_topic",
    "unknown",
}
