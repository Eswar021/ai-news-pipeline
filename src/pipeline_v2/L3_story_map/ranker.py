from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from src.pipeline.L1_collection.common import clean_text, parse_datetime


MAJOR_SOURCES = {
    "OpenAI News",
    "Anthropic News",
    "Anthropic Engineering",
    "Google Research Blog",
    "Google DeepMind Blog",
    "Meta AI Blog",
    "Microsoft AI News",
    "NVIDIA Blog",
    "Hugging Face Blog",
    "AWS Machine Learning Blog",
}


def rank_stories(stories: list[dict]) -> list[dict]:
    ranked = []
    for story in stories:
        score_breakdown = _score_story(story)
        total = sum(score_breakdown.values())
        ranked_story = dict(story)
        ranked_story["rank_score"] = total
        ranked_story["priority_bucket"] = _priority_bucket(total)
        ranked_story["score_breakdown"] = score_breakdown
        ranked.append(ranked_story)

    ranked.sort(key=lambda story: (-story["rank_score"], story["time_range"]["last_seen_at"]), reverse=False)
    for idx, story in enumerate(ranked, start=1):
        story["rank"] = idx
    return ranked


def _score_story(story: dict) -> dict[str, int]:
    records = story["records"]
    groups = Counter(record.get("source_group", "") for record in records)
    official_count = groups.get("ai_company_blogs", 0)
    news_count = groups.get("tech_news_apis", 0)
    research_count = groups.get("research_papers", 0)
    youtube_count = groups.get("youtube_podcast_transcripts", 0)
    community_count = groups.get("community_signals", 0)

    authority = min(official_count * 9 + news_count * 8 + research_count * 6 + community_count * 4 + youtube_count * 4, 30)
    corroboration = min(max(len(records) - 1, 0) * 4, 16)
    diversity = min(max(len({record.get("source_group", "") for record in records}) - 1, 0) * 4, 12)
    recency = _recency_score(story["time_range"]["last_seen_at"])
    traction = min(
        sum(_community_traction(record) for record in records),
        15,
    )
    official_boost = 0 if _is_minor_official_story(story) else (4 if official_count and news_count else (2 if official_count else 0))
    outside_perspective = _outside_perspective_score(story, news_count, research_count, youtube_count)
    research_penalty = 0
    if story["story_type_hint"] == "research_paper" and len(records) == 1:
        research_penalty = -8
    elif story["story_type_hint"] == "research_paper":
        research_penalty = -4
    identity = story.get("story_identity") or {}
    editorial_value = identity.get("editorial_value", "medium")
    editorial_value_score = {
        "high": 4,
        "medium": 0,
        "low": -4,
    }.get(editorial_value, 0)
    story_shape_penalty = 0
    if identity.get("is_noise"):
        story_shape_penalty -= 12
    if identity.get("is_tutorial"):
        story_shape_penalty -= 10
    if identity.get("is_event_update"):
        story_shape_penalty -= 8 if _event_without_concrete_news(story) else 5

    quality_penalty = 0
    if _has_weak_content(story):
        quality_penalty -= 8
    if _is_vendor_tutorial_story(story):
        quality_penalty -= 6

    return {
        "authority": authority,
        "corroboration": corroboration,
        "diversity": diversity,
        "recency": recency,
        "traction": traction,
        "official_boost": official_boost,
        "outside_perspective": outside_perspective,
        "research_penalty": research_penalty,
        "editorial_value": editorial_value_score,
        "story_shape_penalty": story_shape_penalty,
        "quality_penalty": quality_penalty,
    }


def _has_weak_content(story: dict) -> bool:
    for record in story["records"]:
        content = clean_text(record.get("content", ""))
        if record.get("content_status") != "full":
            return True
        if record.get("content_integrity_status") in {"wrong_article", "title_mismatch", "too_short"}:
            return True
        if record.get("source_group") in {"ai_company_blogs", "tech_news_apis"} and len(content) < 700:
            return True
    return False


def _is_vendor_tutorial_story(story: dict) -> bool:
    identity = story.get("story_identity") or {}
    title = clean_text(story.get("story_title", "")).lower()
    tutorial_title = title.startswith(
        (
            "build ",
            "building ",
            "integrating ",
            "prompting ",
            "how to ",
            "using ",
        )
    )
    has_official = any(record.get("source_group") == "ai_company_blogs" for record in story["records"])
    return has_official and (identity.get("is_tutorial") or story.get("story_type_hint") == "tutorial_or_demo" or tutorial_title)


def _is_minor_official_story(story: dict) -> bool:
    if not any(record.get("source_group") == "ai_company_blogs" for record in story["records"]):
        return False
    identity = story.get("story_identity") or {}
    title = clean_text(story.get("story_title", "")).lower()
    if identity.get("editorial_value") == "high" and not identity.get("is_tutorial"):
        return False
    if _is_vendor_tutorial_story(story):
        return True
    return title.startswith(("building ", "integrating ", "prompting ", "nvidia gtc ", "live updates"))


def _event_without_concrete_news(story: dict) -> bool:
    signals = story.get("story_signals") or {}
    products = signals.get("product_counts") or {}
    actions = signals.get("action_counts") or {}
    title = clean_text(story.get("story_title", "")).lower()
    if products or {"launch", "partner", "benchmark"} & set(actions):
        return False
    return "live update" in title or "conference" in title or "computex" in title


def _outside_perspective_score(story: dict, news_count: int, research_count: int, youtube_count: int) -> int:
    identity = story.get("story_identity") or {}
    if identity.get("is_noise") or identity.get("editorial_value") == "low":
        return 0
    score = 0
    if news_count:
        score += 3
    if research_count and story.get("story_type_hint") != "research_paper":
        score += 2
    elif research_count and identity.get("editorial_value") == "high":
        score += 1
    if youtube_count and identity.get("editorial_value") == "high":
        score += 1
    return min(score, 4)


def _community_traction(record: dict) -> int:
    if record.get("provider") == "github":
        stars = int(record.get("stars", 0))
        if stars >= 10000:
            return 6
        if stars >= 1000:
            return 4
        if stars >= 100:
            return 2
        return 1
    score = int(record.get("score", 0))
    comments = int(record.get("comment_count", 0))
    value = 0
    if score >= 500:
        value += 4
    elif score >= 100:
        value += 3
    elif score >= 30:
        value += 2
    elif score > 0:
        value += 1
    if comments >= 100:
        value += 2
    elif comments >= 20:
        value += 1
    return value


def _recency_score(last_seen_at: str) -> int:
    parsed = parse_datetime(last_seen_at)
    if parsed is None:
        return 0
    hours_old = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 3600.0
    if hours_old <= 24:
        return 10
    if hours_old <= 72:
        return 8
    if hours_old <= 168:
        return 5
    return 2


def _priority_bucket(score: int) -> str:
    if score >= 40:
        return "high"
    if score >= 22:
        return "medium"
    return "low"
