from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.pipeline.config import ConfigRepository

from src.pipeline.content.script_generation.formats.roundup.source_truth import build_story_truth_index


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "creator_voice_benchmark"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _json(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_truth_index_scans_full_content_and_preserves_key_metrics() -> None:
    story = _json("story.json")
    sentences = story["records"][0]["content"].split(". ")
    details = []
    for excerpt, values in (
        (sentences[0] + ".", ["0.1 ms"]),
        (sentences[1] + ".", ["2,568 queries", "45 issues", "zero false alarms"]),
        (sentences[2] + ".", ["8x"]),
        (sentences[3] + ".", ["10 out of 10"]),
    ):
        details.extend(
            {
                "record_key": "record_sqlsure_reference",
                "detail_type": "metric",
                "source_note": excerpt,
                "value_text": value,
                "claim_frame": "source_claim",
                "editorial_use": "A concrete project-reported benchmark detail.",
                "visual_role": "counter",
                "visual_opportunity": "Show the reported value with project attribution.",
            }
            for value in values
        )
    details.append(
        {
            "record_key": "record_sqlsure_reference",
            "detail_type": "limitation",
            "source_note": sentences[4],
            "value_text": "",
            "claim_frame": "source_claim",
            "editorial_use": "Preserve that the benchmark is not an independent guarantee.",
            "visual_role": "source_proof",
            "visual_opportunity": "Show the project-reported caveat.",
        }
    )
    index = build_story_truth_index(
        story,
        {
            "story_id": "story_sqlsure_reference",
            "source_synopsis": "Sqlsure reports a small static-analysis benchmark.",
            "central_event": "The project published query analysis and repair results.",
            "source_relationship_summary": "One project-authored record reports the results.",
            "distinctive_details": details,
            "meaning_boundaries": [
                {
                    "record_keys": ["record_sqlsure_reference"],
                    "subject": "Published benchmark results",
                    "established_state": "The project reports results from one bounded benchmark.",
                    "must_not_be_upgraded_to": "A universal guarantee that every query is error-free.",
                    "attribution": "The figures are reported by the project itself.",
                }
            ],
            "tensions_and_caveats": ["The benchmark is not an independent guarantee."],
            "creator_opportunities": ["Contrast fast checks with the limited benchmark scope."],
            "visual_opportunities": ["Show the exact benchmark values."],
        },
    )
    values = {item.value_text for item in index.items if item.value_text}

    assert index.story_id == "story_sqlsure_reference"
    assert {
        "0.1 ms",
        "2,568 queries",
        "45 issues",
        "zero false alarms",
        "8x",
        "10 out of 10",
    } <= values
    assert all(item.record_key == "record_sqlsure_reference" for item in index.items)
    assert any("independent guarantee" in item.source_text for item in index.items)
    assert index.semantic_source_brief["meaning_boundaries"][0]["subject"] == "Published benchmark results"


def test_phase_zero_benchmark_keeps_human_authored_weak_and_strong_examples() -> None:
    baselines = _json("baseline_scripts.json")
    weak = baselines["weak_current_style"]
    strong = baselines["creator_led_reference"]

    assert "Today, we delve" in weak["narration_text"]
    assert "groundbreaking" in weak["narration_text"]
    assert "spell-check" in strong["narration_text"]
    assert "which is rude" in strong["narration_text"]
    assert "source facts repeated in source order" in weak["known_weaknesses"]
    assert "plain-language analogy" in strong["strengths"]
    assert sum(strong["human_reference_scores"].values()) > sum(
        weak["human_reference_scores"].values()
    )


def test_phase_zero_fixture_keeps_human_review_and_visual_regression_cases() -> None:
    regressions = _json("regression_cases.json")

    assert "universal guarantee" in regressions["harmful_review_rewrite"]["expected_guardrail"]
    assert {case["case"] for case in regressions["review_regressions"]} == {
        "empty_issue_rewrite",
        "identical_rewrite",
        "claim_strengthening",
        "future_metric_subject",
        "promotional_rewrite",
    }
    assert regressions["status_semantics"]["expected_guardrail"].startswith(
        "Preserve separate states"
    )
    assert regressions["metadata_regressions"][0]["case"] == "invented_roundup_rivalry"
    assert len(regressions["visual_mismatches"]) == 3
    assert all(case["expected_guardrail"] for case in regressions["visual_mismatches"])


def test_creator_prompts_calibrate_specificity_analogy_and_role_shape() -> None:
    prompt_root = (
        PROJECT_ROOT
        / "src/pipeline/content/script_generation/formats/roundup/prompts/v1"
    )
    writer = (prompt_root / "roundup_story_writer/system.txt").read_text(encoding="utf-8")
    reviewer = (prompt_root / "roundup_story_reviewer/system.txt").read_text(encoding="utf-8")
    researcher = (prompt_root / "roundup_source_researcher/system.txt").read_text(encoding="utf-8")
    director = (prompt_root / "roundup_director/system.txt").read_text(encoding="utf-8")
    bookends = (prompt_root / "roundup_bookend_writer/system.txt").read_text(
        encoding="utf-8"
    )

    assert "a one-million-token context window is like a million books" in writer.lower()
    assert "- lead:" in writer.lower()
    assert "- major:" in writer.lower()
    assert "- brief:" in writer.lower()
    assert "bombshell" in reviewer.lower()
    assert "code published for anyone" in reviewer.lower()
    assert "meaning_boundaries" in researcher
    assert "open-weight" in researcher.lower()
    assert "source_meaning_boundaries" in director
    assert not any(prompt_root.glob("*revision_selector"))
    assert "this particular episode" in bookends.lower()
    assert "money arrived first" in bookends.lower()

    profile = ConfigRepository(
        PROJECT_ROOT / "src/pipeline/config/workbench.yaml"
    ).module("daily_48h_all_sources", "content", "script_generation").value
    guidance = profile["writing_guidance"]
    assert guidance["lead"]["suggested_words"] > guidance["major"]["suggested_words"]
    assert guidance["major"]["suggested_words"] > guidance["brief"]["suggested_words"]
    assert "generic universal conclusions" in " ".join(profile["script_style"]["avoid"])
    assert "candidate_selection" not in profile["review"]

    metadata_prompt = (
        PROJECT_ROOT
        / "src/pipeline/content/metadata_creator/prompts/v1/youtube_metadata_creator/system.txt"
    ).read_text(encoding="utf-8")
    assert "relationship_basis" in metadata_prompt
    assert "open-weight" in metadata_prompt.lower()
    assert "chapter title" in metadata_prompt.lower()
