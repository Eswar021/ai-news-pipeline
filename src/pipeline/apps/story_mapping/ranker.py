from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .contract import RankingConfig
from .utils import clean_text, parse_datetime


def rank_stories(stories: list[dict], ranking_config: dict[str, Any]) -> list[dict]:
    """Attach objective telemetry while preserving the mapper's stable candidate order.

    Editorial ordering is intentionally owned by editorial_selection. The historical
    additive score and priority buckets are no longer used as semantic gates.
    """
    RankingConfig.model_validate(ranking_config)
    described: list[dict] = []
    for index, story in enumerate(stories, start=1):
        next_story = dict(story)
        next_story["rank"] = index
        next_story["rank_score"] = None
        next_story["priority_bucket"] = "unranked"
        next_story["score_breakdown"] = {}
        next_story["ranking_authority"] = "telemetry_only"
        next_story["ranking_features"] = _ranking_features(story)
        next_story["source_authority"] = _source_provenance_summary(story)
        described.append(next_story)
    return described


def _ranking_features(story: dict[str, Any]) -> dict[str, Any]:
    records = list(story.get("records", []))
    groups = Counter(clean_text(record.get("source_group")) or "unknown" for record in records)
    relationships = Counter(
        clean_text(record.get("source_relationship")) or "unknown" for record in records
    )
    last_seen = clean_text((story.get("time_range") or {}).get("last_seen_at"))
    return {
        "record_count": len(records),
        "source_group_counts": dict(groups),
        "source_group_diversity": len(groups),
        "source_relationship_counts": dict(relationships),
        "hours_since_last_seen": _hours_since(last_seen),
        "community_signals": [
            {
                "record_key": clean_text(record.get("record_key")),
                "score": _optional_int(record.get("score")),
                "comment_count": _optional_int(record.get("comment_count")),
                "stars": _optional_int(record.get("stars")),
                "forks": _optional_int(record.get("forks")),
            }
            for record in records
            if any(record.get(key) is not None for key in ("score", "comment_count", "stars", "forks"))
        ],
        "quality_flags": {
            clean_text(record.get("record_key")): dict(record.get("quality_flags") or {})
            for record in records
            if record.get("quality_flags")
        },
        "triage_actions": dict(
            Counter(
                clean_text((record.get("editorial_triage") or {}).get("recommended_action"))
                or "untriaged"
                for record in records
            )
        ),
    }


def _source_provenance_summary(story: dict[str, Any]) -> dict[str, Any]:
    records = list(story.get("records", []))
    return {
        "record_count": len(records),
        "source_relationships": sorted(
            {
                clean_text(record.get("source_relationship")) or "unknown"
                for record in records
            }
        ),
        "source_groups": sorted(
            {clean_text(record.get("source_group")) or "unknown" for record in records}
        ),
    }


def _hours_since(value: str) -> float | None:
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    return round(
        max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 3600.0),
        2,
    )


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
