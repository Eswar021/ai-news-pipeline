from __future__ import annotations

from pathlib import Path

import pytest

from src.pipeline.voiceover.delivery_comparison import (
    DeliveryComparisonConfig,
    extract_sample,
    run_comparison,
)


def _script_result() -> dict:
    return {
        "status": "ok",
        "data": {
            "run_id": "run_demo",
            "script_package": {
                "sections": [
                    {
                        "section_id": "section_00_intro",
                        "section_type": "intro",
                        "narration_text": "Fallback section text.",
                        "beats": [
                            {
                                "beat_id": "intro_beat_01",
                                "narration_text": "The same representative intro text.",
                            },
                            {
                                "beat_id": "intro_beat_02",
                                "narration_text": "This second beat should not be included.",
                            },
                        ],
                    }
                ]
            },
        },
    }


def test_extract_sample_uses_explicit_intro_beats() -> None:
    sample = extract_sample(_script_result(), section_type="intro", beat_count=1)

    assert sample["text"] == "The same representative intro text."
    assert sample["beat_ids"] == ["intro_beat_01"]
    assert sample["section_id"] == "section_00_intro"


def test_comparison_uses_same_text_and_nested_variant_settings(tmp_path: Path) -> None:
    requests: list[dict] = []

    def fake_voiceover_runner(request: dict) -> dict:
        requests.append(request)
        output_dir = Path(request["config"]["output_dir"])
        audio_path = output_dir / "audio" / "full_voiceover.wav"
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(b"demo-wave" * 8)
        return {
            "status": "ok",
            "data": {"run_id": request["run"]["run_id"]},
            "summary": {"duration_seconds": 4.2},
            "handoff": {"ready_for_video_assembly": True},
        }

    config = DeliveryComparisonConfig.model_validate(
        {
            "section_type": "intro",
            "beat_count": 1,
            "variants": [
                {
                    "id": "marin_demo",
                    "label": "Marin Demo",
                    "description": "A short test.",
                    "config": {
                        "provider": "openai",
                        "speed": 0.97,
                        "openai": {"voice": "marin", "instructions": "Expressive but natural."},
                    },
                }
            ],
        }
    )

    result = run_comparison(
        script_result=_script_result(),
        script_source="script_generation_result.json",
        base_voiceover_config={
            "provider": "openai",
            "style": "general_youtube",
            "output_dir": "unused",
            "openai": {
                "model": "gpt-4o-mini-tts",
                "voice": "cedar",
                "instructions": "Baseline.",
            },
        },
        comparison_config=config,
        output_dir=tmp_path,
        voiceover_runner=fake_voiceover_runner,
    )

    assert result["status"] == "ok"
    assert result["variant_count"] == 1
    assert requests[0]["input"]["script_text"] == "The same representative intro text."
    assert requests[0]["config"]["openai"]["model"] == "gpt-4o-mini-tts"
    assert requests[0]["config"]["openai"]["voice"] == "marin"
    assert requests[0]["config"]["speed"] == 0.97
    assert (tmp_path / "samples" / "01_marin_demo.wav").exists()


def test_comparison_uses_configured_default_variants(tmp_path: Path) -> None:
    seen_voices: list[str] = []

    def fake_voiceover_runner(request: dict) -> dict:
        seen_voices.append(request["config"]["openai"]["voice"])
        output_dir = Path(request["config"]["output_dir"])
        audio_path = output_dir / "audio" / "full_voiceover.wav"
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(b"demo-wave")
        return {
            "status": "ok",
            "data": {"run_id": request["run"]["run_id"]},
            "summary": {"duration_seconds": 4.2},
            "handoff": {"ready_for_video_assembly": True},
        }

    config = DeliveryComparisonConfig.model_validate(
        {
            "section_type": "intro",
            "beat_count": 1,
            "default_variant_ids": ["second"],
            "variants": [
                {
                    "id": "first",
                    "label": "First",
                    "description": "Not selected by default.",
                    "config": {"provider": "openai", "openai": {"voice": "cedar"}},
                },
                {
                    "id": "second",
                    "label": "Second",
                    "description": "Selected by default.",
                    "config": {"provider": "openai", "openai": {"voice": "marin"}},
                },
            ],
        }
    )

    result = run_comparison(
        script_result=_script_result(),
        script_source="script_generation_result.json",
        base_voiceover_config={"provider": "openai", "output_dir": "unused"},
        comparison_config=config,
        output_dir=tmp_path,
        voiceover_runner=fake_voiceover_runner,
    )

    assert result["variant_count"] == 1
    assert result["variants"][0]["variant_id"] == "second"
    assert seen_voices == ["marin"]


def test_comparison_expands_voice_by_direction_matrix(tmp_path: Path) -> None:
    requests: list[dict] = []

    def fake_voiceover_runner(request: dict) -> dict:
        requests.append(request)
        output_dir = Path(request["config"]["output_dir"])
        audio_path = output_dir / "audio" / "full_voiceover.wav"
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(b"demo-wave")
        return {
            "status": "ok",
            "data": {"run_id": request["run"]["run_id"]},
            "summary": {"duration_seconds": 4.2},
            "handoff": {"ready_for_video_assembly": True},
        }

    config = DeliveryComparisonConfig.model_validate(
        {
            "section_type": "intro",
            "beat_count": 1,
            "variants": [],
            "matrices": [
                {
                    "id": "gemini_matrix",
                    "label": "Gemini Matrix",
                    "provider": "gemini",
                    "model": "gemini-test-tts",
                    "provider_config": {"worker_count": 1},
                    "pricing": {
                        "text_input_usd_per_million_tokens": 1.0,
                        "audio_output_usd_per_million_tokens": 20.0,
                        "audio_tokens_per_second": 25.0,
                        "projected_audio_seconds": 20.0,
                    },
                    "voices": [
                        {"id": "kore", "voice": "Kore", "label": "Kore", "character": "Firm"},
                        {"id": "achird", "voice": "Achird", "label": "Achird", "character": "Friendly"},
                    ],
                    "directions": [
                        {
                            "id": "dynamic",
                            "label": "Dynamic",
                            "description": "Energetic",
                            "speed": 0.99,
                            "instructions": "Use energetic contrast.",
                            "transcript_prefix": "[excitedly]",
                        },
                        {
                            "id": "warm",
                            "label": "Warm",
                            "description": "Conversational",
                            "speed": 0.96,
                            "instructions": "Use warm curiosity.",
                        },
                    ],
                }
            ],
        }
    )

    result = run_comparison(
        script_result=_script_result(),
        script_source="script_generation_result.json",
        base_voiceover_config={"provider": "gemini", "output_dir": "unused"},
        comparison_config=config,
        output_dir=tmp_path,
        selected_matrix_ids=["gemini_matrix"],
        voiceover_runner=fake_voiceover_runner,
    )

    assert result["status"] == "ok"
    assert result["requested_variant_count"] == 4
    assert [request["config"]["gemini"]["voice"] for request in requests] == [
        "Kore",
        "Kore",
        "Achird",
        "Achird",
    ]
    assert requests[0]["config"]["gemini"]["instructions"] == "Use energetic contrast."
    assert requests[0]["input"]["script_text"].startswith("[excitedly] ")
    assert requests[1]["config"]["speed"] == 0.96
    assert result["variants"][0]["actual_wpm"] == pytest.approx(71.4, abs=0.1)
    assert result["projected_cost_usd"] > 0
    assert result["estimated_cost_usd"] > 0
    assert (tmp_path / "comparison_summary.md").exists()
    assert (tmp_path / "comparison_summary.csv").exists()
    assert (tmp_path / "comparison_playlist.m3u8").exists()


def test_comparison_resume_reuses_successful_sample(tmp_path: Path) -> None:
    calls = 0

    def fake_voiceover_runner(request: dict) -> dict:
        nonlocal calls
        calls += 1
        output_dir = Path(request["config"]["output_dir"])
        audio_path = output_dir / "audio" / "full_voiceover.wav"
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(b"demo-wave" * 8)
        return {
            "status": "ok",
            "data": {"run_id": request["run"]["run_id"]},
            "summary": {"duration_seconds": 4.2},
            "handoff": {"ready_for_video_assembly": True},
        }

    config = DeliveryComparisonConfig.model_validate(
        {
            "variants": [
                {
                    "id": "resume_demo",
                    "label": "Resume Demo",
                    "description": "A reusable sample.",
                    "config": {"provider": "openai", "openai": {"voice": "marin"}},
                }
            ]
        }
    )
    common = {
        "script_result": _script_result(),
        "script_source": "script_generation_result.json",
        "base_voiceover_config": {"provider": "openai", "output_dir": "unused"},
        "comparison_config": config,
        "output_dir": tmp_path,
        "voiceover_runner": fake_voiceover_runner,
    }

    first = run_comparison(**common)
    second = run_comparison(**common, resume=True)

    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert calls == 1
    assert second["variants"][0]["variant_id"] == "resume_demo"


def test_comparison_rejects_matrix_above_cost_cap(tmp_path: Path) -> None:
    config = DeliveryComparisonConfig.model_validate(
        {
            "max_projected_cost_usd": 0.001,
            "variants": [],
            "matrices": [
                {
                    "id": "priced_matrix",
                    "label": "Priced Matrix",
                    "provider": "gemini",
                    "model": "gemini-test-tts",
                    "pricing": {
                        "text_input_usd_per_million_tokens": 1.0,
                        "audio_output_usd_per_million_tokens": 20.0,
                        "audio_tokens_per_second": 25.0,
                        "projected_audio_seconds": 20.0,
                    },
                    "voices": [
                        {"id": "kore", "voice": "Kore", "label": "Kore", "character": "Firm"}
                    ],
                    "directions": [
                        {
                            "id": "fast",
                            "label": "Fast",
                            "description": "Fast creator",
                            "speed": 1.1,
                            "instructions": "Speak quickly and clearly.",
                        }
                    ],
                }
            ],
        }
    )

    with pytest.raises(ValueError, match="exceeds configured cap"):
        run_comparison(
            script_result=_script_result(),
            script_source="script_generation_result.json",
            base_voiceover_config={"provider": "gemini", "output_dir": "unused"},
            comparison_config=config,
            output_dir=tmp_path,
            selected_matrix_ids=["priced_matrix"],
            voiceover_runner=lambda _request: {},
        )
