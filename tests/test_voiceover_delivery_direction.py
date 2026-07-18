from __future__ import annotations

from src.pipeline.voiceover.delivery import compose_delivery_instructions
from src.pipeline.voiceover.script_units import _beat_chunks


def _direction() -> dict:
    return {
        "performance_intent": "Build curiosity, then make the contrast land.",
        "emotional_color": "lightly amused",
        "pace": "brisk",
        "energy": "animated",
        "emphasis_phrases": ["the strange part"],
        "pause_after": "short",
    }


def test_script_beat_delivery_direction_survives_provider_chunking() -> None:
    chunks = _beat_chunks(
        sections=[
            {
                "section_id": "section_01_story",
                "section_type": "story",
                "story_id": "story_fixture",
                "story_title": "A useful contradiction",
                "beats": [
                    {
                        "beat_id": "section_01_story_beat_01",
                        "beat_order": 1,
                        "beat_type": "what_changed",
                        "beat_function": "reveal",
                        "narration_text": "The strange part is that the smaller model finished first.",
                        "delivery_direction": _direction(),
                    }
                ],
            }
        ],
        chunking={
            "max_chars": 500,
            "max_sentences_per_chunk": 2,
            "chunk_pause_seconds": 0.1,
            "paragraph_pause_seconds": 0.2,
        },
        beat_pause_seconds=0.08,
        section_pause_seconds=0.32,
        require_script_beats=True,
    )

    assert len(chunks) == 1
    assert chunks[0]["text"] == "The strange part is that the smaller model finished first."
    assert chunks[0]["delivery_direction"] == _direction()


def test_provider_adapter_translates_delivery_without_altering_transcript() -> None:
    chunk = {
        "text": "The strange part is that the smaller model finished first.",
        "delivery_direction": _direction(),
    }
    instructions = compose_delivery_instructions(
        base_instructions="Speak as a conversational technology creator.",
        chunk=chunk,
        provider="gemini",
        config={"enabled": True, "apply_to_providers": ["gemini", "openai"]},
    )

    assert chunk["text"] == "The strange part is that the smaller model finished first."
    assert "Beat-specific performance direction" in instructions
    assert "lightly amused" in instructions
    assert "the strange part" in instructions
    assert "End pause: short" in instructions


def test_delivery_can_be_disabled_per_provider() -> None:
    base = "Speak naturally."
    instructions = compose_delivery_instructions(
        base_instructions=base,
        chunk={"text": "A beat.", "delivery_direction": _direction()},
        provider="kokoro_local",
        config={"enabled": True, "apply_to_providers": ["gemini", "openai"]},
    )

    assert instructions == base
