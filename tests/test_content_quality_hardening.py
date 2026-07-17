from __future__ import annotations

from pathlib import Path

import yaml

from src.pipeline.apps.evidence_prep.utils import clean_article_content
from src.pipeline.apps.metadata_creator.app import _build_tags, _chapter_title, _clean_title_options
from src.pipeline.apps.metadata_finalizer.app import _chapter_title as finalized_chapter_title
from src.pipeline.apps.script_generation.formats.roundup.source_truth import (
    build_story_truth_index,
    compact_truth_index,
)
from src.pipeline.apps.story_mapping.story_label import validate_story_label


ROOT = Path(__file__).parents[1]


def _profile() -> dict:
    workbench = yaml.safe_load((ROOT / "src/pipeline/config/workbench.yaml").read_text(encoding="utf-8"))
    return workbench["profiles"][workbench["default_run_profile"]]


def test_domain_scoped_cleaner_removes_article_chrome_without_losing_body() -> None:
    content = (
        "Listen to this article in summarized format Subscribe now TIMESOFINDIA.COM "
        "A student built an AI receptionist after noticing missed calls. "
        "ALSO READ: An unrelated celebrity story? How did she build it? "
        "She split the code into testable pieces. Add as a Reliable and Trusted News Source "
        "Read More News on unrelated market stories"
    )

    cleaned, details = clean_article_content(
        content,
        url="https://economictimes.indiatimes.com/news/example/articleshow/1.cms",
        config=_profile()["evidence_prep"]["content_cleaning"],
    )

    assert cleaned.startswith("A student built an AI receptionist")
    assert "unrelated celebrity" not in cleaned
    assert "She split the code into testable pieces" in cleaned
    assert "Reliable and Trusted" not in cleaned
    assert details["modified"] is True
    assert details["removed_chars"] > 0


def test_verge_and_techcrunch_cleaners_remove_page_chrome() -> None:
    config = _profile()["evidence_prep"]["content_cleaning"]
    verge = (
        "Tech AI News Example title Example subtitle by Alex Reporter Jul 13, 2026 UTC "
        "Link Share Gift Image: Example Alex Reporter is the Verge's weekend editor. "
        "They have covered technology for years. The product is recruiting a safety lead. "
        "Follow topics and authors from this story Most Popular Advertiser Content"
    )
    techcrunch = (
        "OpenAI is hiring a product manager through a job posting. "
        "The role focuses on family experiences. Topics AI, OpenAI "
        "When you purchase through links in our articles, we may earn a commission. Most Popular"
    )

    cleaned_verge, verge_details = clean_article_content(
        verge,
        url="https://www.theverge.com/ai/example",
        config=config,
    )
    cleaned_techcrunch, techcrunch_details = clean_article_content(
        techcrunch,
        url="https://techcrunch.com/2026/07/13/example",
        config=config,
    )

    assert cleaned_verge.startswith("The product is recruiting a safety lead")
    assert "Most Popular" not in cleaned_verge
    assert cleaned_techcrunch == (
        "OpenAI is hiring a product manager through a job posting. "
        "The role focuses on family experiences."
    )
    assert verge_details["applied_rule"] == "the_verge_article_chrome"
    assert techcrunch_details["applied_rule"] == "techcrunch_article_chrome"


def test_generic_html_normalization_preserves_body_text_and_removes_markup() -> None:
    cleaned, details = clean_article_content(
        (
            "<article><h1>Agent benchmark</h1><p>The test repaired 10 of 10 cases.</p>"
            "<ol><li>Run the sandbox.</li><li>Inspect the trace.</li></ol>"
            "<script>window.metric = 2026;</script></article>"
        ),
        url="https://example.com/agent-benchmark",
        config=_profile()["evidence_prep"]["content_cleaning"],
    )

    assert cleaned == (
        "Agent benchmark The test repaired 10 of 10 cases. "
        "Run the sandbox. Inspect the trace."
    )
    assert "<" not in cleaned
    assert "window.metric" not in cleaned
    assert details["html_markup_removed"] is True
    assert details["html_tag_count"] > 0
    assert details["applied_rule"] == "generic_html_to_text"


def test_evidence_prep_has_no_code_owned_topic_filter_policy() -> None:
    config = _profile()["evidence_prep"]

    assert "filter_policy" not in config
    assert "source_classification" not in config


def test_truth_context_prioritizes_body_and_removes_repeated_chrome() -> None:
    cleaned_content, _ = clean_article_content(
        (
            "OpenAI is hiring a product manager through a job posting. "
            "The role focuses on families and caregivers. "
            "Follow topics and authors from this story. Most Popular Most Popular."
        ),
        url="https://www.theverge.com/ai/example",
        config=_profile()["evidence_prep"]["content_cleaning"],
    )
    story = {
        "story_id": "story_hiring",
        "records": [
            {
                "record_key": "record_hiring",
                "title": "OpenAI expands its family focus",
                "description": "ChatGPT has a new hire for families.",
                "content": cleaned_content,
                "url": "https://www.theverge.com/ai/example",
            }
        ],
    }

    compact = compact_truth_index(
        build_story_truth_index(
            story,
            {
                "story_id": "story_hiring",
                "source_synopsis": "OpenAI is hiring for family-focused product work.",
                "central_event": "A product-manager role focuses on families and caregivers.",
                "source_relationship_summary": "One third-party article reports the job posting.",
                "distinctive_details": [
                    {
                        "record_key": "record_hiring",
                        "detail_type": "event",
                        "source_note": "OpenAI is hiring a product manager through a job posting.",
                        "value_text": "",
                        "claim_frame": "reported_fact",
                        "editorial_use": "Anchor the story in the actual hiring action.",
                        "visual_role": "source_proof",
                        "visual_opportunity": "Show the source sentence.",
                    }
                ],
                "tensions_and_caveats": [],
                "creator_opportunities": ["Explain what the role signals."],
                "visual_opportunities": ["Show the job-posting source."],
            },
        )
    )

    assert compact["items"][0]["source_text"].startswith("OpenAI is hiring")
    assert compact["items"][0]["source_field"] == "semantic_source_brief"
    assert not any("Most Popular" in item["source_text"] for item in compact["items"])
    assert len({item["source_text"].casefold() for item in compact["items"]}) == len(compact["items"])


def test_metadata_keeps_llm_title_judgment_and_applies_only_stable_cleanup() -> None:
    titles = _clean_title_options(
        [
            {
                "title": "How AI Is Shaping Our Future",
                "accuracy_risk": "low",
                "click_potential": "high",
                "why_it_works": "Broad roundup framing.",
            },
            {
                "title": "How AI Is Shaping Our Future",
                "accuracy_risk": "high",
                "click_potential": "low",
                "why_it_works": "Duplicate.",
            },
            {
                "title": "Apple's Car Failure Built Its AI Chip Strategy",
                "accuracy_risk": "low",
                "click_potential": "high",
                "why_it_works": "Specific.",
            },
        ],
        8,
    )
    section = {
        "section_type": "story",
        "story_title": "Apple's failed self-driving car program left a legacy of powerful AI chips",
        "title_card": {"display_title": "Apple's Car Failure Became an AI Chip Strategy"},
    }
    tags = _build_tags(
        ["AI", "Github.io"],
        {"stories": []},
        20,
        blocked_tags=["github.io"],
    )

    assert [item["title"] for item in titles] == [
        "How AI Is Shaping Our Future",
        "Apple's Car Failure Built Its AI Chip Strategy",
    ]
    assert _chapter_title(section) == "Apple's Car Failure Became an AI Chip Strategy"
    assert "Github.io" not in tags


def test_story_label_preserves_complete_why_it_matters_sentence() -> None:
    why_it_matters = (
        "This complete explanation is intentionally longer than the historical cutoff, "
        "and downstream packaging must preserve the model's full editorial thought."
    )

    label = validate_story_label(
        {
            "primary_entity": "Acme",
            "owning_org": "Acme",
            "product_or_project": "Agent One",
            "story_action": "launched",
            "story_type": "official_update",
            "temporal_relationship": "same_event",
            "canonical_story_key": "acme|agent_one|launch",
            "one_sentence_story": "Acme launched Agent One.",
            "editorial_value": "high",
            "is_tutorial": False,
            "is_event_update": False,
            "is_noise": False,
            "why_it_matters": why_it_matters,
        },
        {"story_id": "story_acme", "story_title": "Acme launches Agent One"},
    )

    assert label["why_it_matters"] == why_it_matters


def test_finalized_chapter_title_never_cuts_through_a_word() -> None:
    title = "A deliberately long chapter title about a complete product announcement and its practical consequences"

    shortened = finalized_chapter_title(
        {"section_type": "story", "chapter_title": title}
    )

    assert shortened.endswith("…")
    assert shortened[:-1] in title
    assert title.startswith(shortened[:-1])
