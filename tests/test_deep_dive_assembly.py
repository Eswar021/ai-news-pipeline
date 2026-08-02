"""deep_dive deterministic core: section planning + assembly + checks (no LLM)."""
from __future__ import annotations

from src.pipeline.content.script_generation.formats.deep_dive import app as deep_dive_app  # import smoke
from src.pipeline.content.script_generation.formats.deep_dive.assembler import assemble_script
from src.pipeline.content.script_generation.formats.deep_dive.checks import check_script_package
from src.pipeline.content.script_generation.formats.deep_dive.sections import build_deep_dive_section_inputs


def _story() -> dict:
    return {
        "story_id": "story_topic",
        "story_identity": {"one_sentence_story": "A single AI topic worth a deep dive.", "primary_entity": "Example"},
        "records": [{"record_key": "r1"}, {"record_key": "r2"}],
        "video_segment": {"segment_order": 1, "role": "lead", "source_record_keys": ["r1", "r2"]},
    }


def _config() -> dict:
    guidance = {"suggested_words": 80, "beat_guidance": "Use focused beats.", "editorial_goal": "Advance the angle."}
    return {
        "script_style": {"audience": "curious builders", "tone": "sharp", "avoid": []},
        "writing_guidance": {"intro": dict(guidance), "angle": dict(guidance), "closing": dict(guidance)},
    }


def _director() -> dict:
    def brief(angle_id: str, label: str) -> dict:
        return {
            "angle_id": angle_id,
            "angle_label": label,
            "angle_engine": "technical_mechanism",
            "angle_promise": f"Explain {label}.",
            "hook_or_bridge": "Bridge naturally.",
            "tension": "t",
            "reveal_or_payoff": "p",
            "viewer_stakes": "s",
            "specific_detail_anchor": "the concrete detail",
            "source_meaning_boundaries": [],
            "must_communicate_truth_ids": [],
            "optional_truth_ids": [],
            "narrator_take": "a real take",
            "explanation_goal": "make it clear",
            "analogy_opportunities": [],
            "humor_opportunities": [],
            "avoid": [],
        }

    return {
        "episode_thesis": "One topic, several facets.",
        "viewer_promise": "You'll understand it fully.",
        "hook_strategy": "open on the odd detail",
        "pacing_strategy": "build",
        "topic_arc": "what happened -> how it works",
        "ordered_angle_ids": ["angle_01", "angle_02"],
        "angle_briefs": [brief("angle_01", "What happened"), brief("angle_02", "How it works")],
    }


def _beat(text: str) -> dict:
    return {"beat_type": "explanation", "beat_function": "explanation", "narration_text": text,
            "source_record_keys": ["r1"], "support_truth_ids": [], "creative_device": "none"}


def _segment(angle_id: str, title: str, text: str) -> dict:
    return {"angle_id": angle_id, "story_id": "story_topic", "display_title": title,
            "story_thesis": "thesis", "viewer_takeaway": "takeaway", "beats": [_beat(text)]}


def test_deep_dive_sections_and_assembly_produce_a_valid_package() -> None:
    story, config, director = _story(), _config(), _director()
    section_plan = build_deep_dive_section_inputs(story, director, config)
    assert [s["section_type"] for s in section_plan] == ["intro", "story", "story", "closing"]
    assert [s.get("angle_id") for s in section_plan] == [None, "angle_01", "angle_02", None]

    angle_segments = [_segment("angle_01", "What happened", "Here is what happened."),
                      _segment("angle_02", "How it works", "Here is how it works.")]
    bookends = {
        "intro_beats": [{"beat_type": "hook", "narration_text": "A striking opener."}],
        "closing_beats": [{"beat_type": "conclusion", "narration_text": "The honest takeaway."}],
        "continuity_notes": [],
    }
    assembled = assemble_script(section_plan=section_plan, director=director, angle_segments=angle_segments,
                                bookends=bookends, words_per_minute=140, title_card_seconds=2.8)
    sections = assembled["sections"]
    assert len(sections) == 4
    # angle sections carry title cards labelled by the angle; bookends do not.
    assert sections[1]["title_card"]["display_title"] == "What happened"
    assert sections[2]["title_card"]["display_title"] == "How it works"
    assert sections[0]["title_card"] is None and sections[-1]["title_card"] is None
    assert assembled["full_script"].startswith("A striking opener.")
    assert len(assembled["audio_plan"]["units"]) == 4

    package = {"angle_count": 2, "sections": sections, "full_script": assembled["full_script"]}
    result = check_script_package(package, {"stories": [story]})
    assert result["passed"], result["errors"]


def test_app_module_exposes_run() -> None:
    assert callable(deep_dive_app.run)
