from __future__ import annotations


APP_NAME = "news_collection"
PROFILES_FILE = "profiles.yaml"
SOURCE_CONFIG_FILE = "source_config.yaml"

SUPPORTED_SOURCE_GROUPS = frozenset(
    {
        "ai_company_blogs",
        "tech_news_apis",
        "research_papers",
        "youtube_podcast_transcripts",
        "community_signals",
    }
)

COLLECTION_WINDOW_REQUIRED_GROUPS = frozenset(
    {
        "tech_news_apis",
        "youtube_podcast_transcripts",
        "community_signals",
    }
)
