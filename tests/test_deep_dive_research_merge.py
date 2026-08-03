"""Folding a research dossier into the deep_dive story as citable synthetic records."""
from __future__ import annotations

import copy

from src.pipeline.content.script_generation.formats.deep_dive.research_merge import (
    build_research_brief,
    merge_dossier_into_story,
)
from src.pipeline.content.script_generation.shared.utils import source_record_keys

_STORY = {
    "story_id": "story_astra",
    "story_title": "OpenAI Astra",
    "records": [{"record_key": "record_article", "title": "TechCrunch", "url": "https://tc.com/a"}],
    "video_segment": {"source_record_keys": ["record_article"]},
}

_DOSSIER = {
    "topic": "OpenAI Astra",
    "summary": "Astra is a research model that solved ten unsolved problems.",
    "claims": [
        {"claim": "Astra solved 10 open problems", "evidence": "per the paper", "source_url": "https://cdn.openai.com/astra.pdf"},
        {"claim": "no source", "source_url": ""},  # dropped: ungrounded
    ],
    "quotes": [{"text": "a milestone", "speaker": "Sutskever", "source_url": "https://cdn.openai.com/astra.pdf"}],
    "numbers": [{"value": "$2,000", "context": "compute per problem", "source_url": "https://aiweekly.co/astra"}],
    "counterpoints": [{"point": "results are not independently reproduced", "source_url": "https://aiweekly.co/astra"}],
    "timeline": [{"date": "2026-07", "event": "Astra announced"}],
    "angles": [{"angle": "How the solver works", "why": "the mechanism is the story"}],
    "sources": [
        {"url": "https://cdn.openai.com/astra.pdf", "title": "OpenAI Astra paper"},
        {"url": "https://aiweekly.co/astra", "title": "AI Weekly"},
    ],
}


def test_grounded_items_become_citable_synthetic_records() -> None:
    original = copy.deepcopy(_STORY)
    story, _brief = merge_dossier_into_story(_STORY, _DOSSIER)

    assert _STORY == original, "input story must not be mutated"

    research_records = [r for r in story["records"] if r["record_key"].startswith("research_src_")]
    assert len(research_records) == 2  # one per unique grounded source_url

    by_url = {r["url"]: r for r in research_records}
    pdf = by_url["https://cdn.openai.com/astra.pdf"]
    assert pdf["title"] == "OpenAI Astra paper"
    assert "Astra solved 10 open problems" in pdf["content"]
    assert '"a milestone"' in pdf["content"]  # quote grouped under same source
    assert pdf["source_relationship"] == "web_research"

    weekly = by_url["https://aiweekly.co/astra"]
    assert "$2,000" in weekly["content"] and "not independently reproduced" in weekly["content"]

    # Citable through the SAME allow-list the writer enforces.
    keys = source_record_keys(story)
    assert "record_article" in keys
    assert {r["record_key"] for r in research_records} <= set(keys)


def test_ungrounded_items_are_dropped() -> None:
    _, _ = merge_dossier_into_story(_STORY, _DOSSIER)
    story, _brief = merge_dossier_into_story(_STORY, _DOSSIER)
    joined = " ".join(r["content"] for r in story["records"] if r["record_key"].startswith("research_src_"))
    assert "no source" not in joined  # the claim with an empty source_url never lands


def test_research_brief_carries_framing_only() -> None:
    brief = build_research_brief(_DOSSIER)
    assert brief["topic_summary"].startswith("Astra is a research model")
    assert brief["suggested_angles"][0]["angle"] == "How the solver works"
    assert brief["timeline"][0]["event"] == "Astra announced"
    # framing is not facts: no source_url / claim leakage
    assert "claims" not in brief and "numbers" not in brief


def test_empty_dossier_leaves_story_unchanged() -> None:
    story, brief = merge_dossier_into_story(_STORY, {})
    assert story is _STORY  # no grounded items → returned as-is
    assert brief == {}


def test_dossier_with_only_framing_adds_no_records_but_returns_brief() -> None:
    dossier = {"summary": "just a summary", "angles": [{"angle": "a", "why": "b"}]}
    story, brief = merge_dossier_into_story(_STORY, dossier)
    assert story is _STORY  # no grounded (sourced) items → no synthetic records
    assert brief["topic_summary"] == "just a summary"
