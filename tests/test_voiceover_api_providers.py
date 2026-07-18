from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import wave

import pytest

from src.pipeline.orchestration.stages.voiceover import _voiceover_variant
from src.pipeline.voiceover.contract import VoiceoverConfig
from src.pipeline.voiceover.providers import gemini_tts, openai_tts


def _write_test_wav(path: Path, *, frame_count: int = 2400) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes(b"\x00\x00" * frame_count)


def _api_kwargs(tmp_path: Path) -> dict:
    return {
        "chunks": [
            {"chunk_id": "chunk_001", "text": "First sentence."},
            {"chunk_id": "chunk_002", "text": "Second sentence."},
        ],
        "output_dir": tmp_path,
        "instructions": "Conversational and clear.",
        "speed": 1.0,
        "api_key_envs": ["TEST_TTS_API_KEY"],
        "request_timeout_seconds": 10.0,
        "max_retries": 1,
        "retry_initial_delay_seconds": 0.001,
        "retry_max_delay_seconds": 0.001,
        "worker_count": 2,
        "max_input_chars": 4096,
        "sample_rate_hz": 24000,
    }


def test_openai_provider_writes_ordered_wav_chunks(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict] = []

    class Response:
        def __init__(self, request: dict) -> None:
            self.request = request

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def stream_to_file(self, path: Path) -> None:
            _write_test_wav(Path(path))

    def create(**kwargs):
        calls.append(kwargs)
        return Response(kwargs)

    client = SimpleNamespace(
        audio=SimpleNamespace(
            speech=SimpleNamespace(
                with_streaming_response=SimpleNamespace(create=create)
            )
        )
    )
    monkeypatch.setenv("TEST_TTS_API_KEY", "test-key")
    monkeypatch.setattr(openai_tts, "_make_client", lambda **_kwargs: client)

    result = openai_tts.synthesize_chunks_to_wav(
        **_api_kwargs(tmp_path),
        model="gpt-4o-mini-tts",
        voice="cedar",
        response_format="wav",
    )

    assert [Path(item["audio_path"]).name for item in result] == ["chunk_001.wav", "chunk_002.wav"]
    assert all(item["sample_rate_hz"] == 24000 for item in result)
    assert {call["input"] for call in calls} == {"First sentence.", "Second sentence."}
    assert all(call["voice"] == "cedar" for call in calls)
    assert all(call["instructions"] == "Conversational and clear." for call in calls)


def test_gemini_provider_wraps_pcm_and_routes_voice(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict] = []

    class Struct:
        def __init__(self, **kwargs) -> None:
            self.values = kwargs

    class Models:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            inline_data = SimpleNamespace(data=b"\x00\x00" * 2400, mime_type="audio/L16;rate=24000")
            part = SimpleNamespace(inline_data=inline_data)
            return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])

    fake_types = SimpleNamespace(
        GenerateContentConfig=Struct,
        SpeechConfig=Struct,
        VoiceConfig=Struct,
        PrebuiltVoiceConfig=Struct,
    )
    monkeypatch.setenv("TEST_TTS_API_KEY", "test-key")
    monkeypatch.setattr(
        gemini_tts,
        "_make_client",
        lambda **_kwargs: (SimpleNamespace(models=Models()), fake_types),
    )

    result = gemini_tts.synthesize_chunks_to_wav(
        **_api_kwargs(tmp_path),
        model="gemini-2.5-flash-preview-tts",
        voice="Kore",
        language_code="en-US",
    )

    assert [Path(item["audio_path"]).name for item in result] == ["chunk_001.wav", "chunk_002.wav"]
    assert all(item["duration_seconds"] == pytest.approx(0.1) for item in result)
    assert {call["contents"].split("### TRANSCRIPT\n", 1)[1] for call in calls} == {
        "First sentence.",
        "Second sentence.",
    }
    assert all("Conversational and clear." in call["contents"] for call in calls)
    assert all("# AUDIO PROFILE" in call["contents"] for call in calls)
    assert all("Pace target: approximately 1.00x" in call["contents"] for call in calls)
    speech_config = calls[0]["config"].values["speech_config"]
    voice_config = speech_config.values["voice_config"]
    assert voice_config.values["prebuilt_voice_config"].values["voice_name"] == "Kore"


def test_api_voiceover_contract_rejects_unsupported_sample_rate(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sample_rate_hz=24000"):
        VoiceoverConfig.model_validate(
            {
                "provider": "openai",
                "style": "general_youtube",
                "sample_rate_hz": 48000,
                "output_dir": str(tmp_path),
            }
        )


def test_gemini_contract_prefers_dedicated_tts_key(tmp_path: Path) -> None:
    config = VoiceoverConfig.model_validate(
        {
            "provider": "gemini",
            "style": "general_youtube",
            "sample_rate_hz": 24000,
            "output_dir": str(tmp_path),
        }
    )

    assert config.gemini.api_key_envs == [
        "GEMINI_TTS_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    ]


def test_api_voiceover_variant_changes_with_delivery_config() -> None:
    base = {
        "provider": "openai",
        "style": "general_youtube",
        "voice": None,
        "speed": 1.0,
        "sample_rate_hz": 24000,
        "chunking": {},
        "alignment": {},
        "mastering": {},
        "captions": {},
        "openai": {
            "model": "gpt-4o-mini-tts",
            "voice": "cedar",
            "instructions": "Conversational.",
        },
    }
    script_package = {"generation_source": "app"}
    provenance = {"script_fingerprint": "sha256:" + "a" * 64}

    first = _voiceover_variant(base, script_package, provenance)
    changed = {**base, "openai": {**base["openai"], "instructions": "Documentary."}}
    second = _voiceover_variant(changed, script_package, provenance)

    assert "gpt_4o_mini_tts" in first
    assert "cedar" in first
    assert first != second
