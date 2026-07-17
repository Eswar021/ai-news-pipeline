from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from src.pipeline.apps.story_mapping.contract import RankingConfig
from src.pipeline.apps.story_mapping.ranker import rank_stories
from src.pipeline.apps.video_packaging.formats.roundup import build_roundup_packet


def test_story_mapping_preserves_candidate_order_and_attaches_telemetry_only() -> None:
    stories = [_single_source_story(index) for index in range(1, 4)]

    described = rank_stories(stories, {"mode": "telemetry_only"})

    assert [story["story_id"] for story in described] == [
        "story_news_1",
        "story_news_2",
        "story_news_3",
    ]
    assert [story["rank"] for story in described] == [1, 2, 3]
    assert all(story["rank_score"] is None for story in described)
    assert {story["priority_bucket"] for story in described} == {"unranked"}
    assert {story["ranking_authority"] for story in described} == {"telemetry_only"}


def test_self_published_provenance_is_visible_but_not_semantically_penalized() -> None:
    story = _single_source_story(1)
    story["story_title"] = "Show HN: Example agent sandbox"
    story["records"][0].update(
        {
            "title": story["story_title"],
            "url": "https://example-project.github.io/demo",
            "source_relationship": "community_launch",
            "stars": 42,
        }
    )

    described = rank_stories([story], {"mode": "telemetry_only"})[0]

    assert described["rank_score"] is None
    assert described["priority_bucket"] == "unranked"
    assert described["source_authority"]["source_relationships"] == ["community_launch"]
    assert described["ranking_features"]["community_signals"][0]["stars"] == 42


def test_video_packaging_preserves_editorial_selector_order_and_roles() -> None:
    stories = [_single_source_story(index) for index in range(1, 4)]
    roles = ["lead", "major", "brief"]
    selected = []
    for order, (story, role) in enumerate(zip(stories, roles, strict=True), start=1):
        selected.append(
            {
                **story,
                "editorial_selection": {
                    "story_id": story["story_id"],
                    "role": role,
                    "selection_order": order,
                    "selection_reason": "Semantic editorial choice.",
                },
            }
        )
    slate = {
        "episode_shape": "mixed_news_roundup",
        "episode_thesis": "",
        "ordering_rationale": "Lead with the clearest viewer payoff.",
        "selected_stories": selected,
        "reserve": [],
        "rejected": [],
    }

    result = build_roundup_packet(
        slate,
        {"min_stories": 3, "max_stories": 5, "duration_mode": "content_driven"},
    )

    assert result["packet"]["selected_story_ids"] == [story["story_id"] for story in stories]
    assert [story["video_segment"]["role"] for story in result["packet"]["stories"]] == roles
    assert result["selection_stats"]["selection_authority"] == "editorial_selection_llm"


def test_ranking_contract_rejects_semantic_scoring_mode() -> None:
    with pytest.raises(ValueError):
        RankingConfig.model_validate({"mode": "additive_score"})


def _single_source_story(index: int) -> dict:
    story = {
        "story_id": f"story_news_{index}",
        "story_title": f"Fresh AI news story {index}",
        "story_type_hint": "industry_news",
        "story_identity": {
            "primary_entity": f"Entity {index}",
            "product_or_project": f"Product {index}",
            "canonical_story_key": f"entity-{index}|product-{index}|launch",
            "editorial_value": "medium",
            "is_noise": False,
            "is_tutorial": False,
            "is_event_update": False,
        },
        "records": [
            {
                "record_key": f"record_news_{index}",
                "source_group": "tech_news_apis",
                "source_relationship": "independent_report",
                "content_status": "full",
                "content_integrity_status": "ok",
                "content": "A" * 900,
            }
        ],
        "record_count": 1,
        "source_groups": ["tech_news_apis"],
        "time_range": {
            "first_seen_at": datetime.now(timezone.utc).isoformat(),
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
            "time_span_hours": 0.0,
        },
    }
    return deepcopy(story)
