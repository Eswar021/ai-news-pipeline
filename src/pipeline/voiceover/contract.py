from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import (
    DEFAULT_CHATTERBOX_CFG_WEIGHT,
    DEFAULT_CHATTERBOX_DEVICE,
    DEFAULT_CHATTERBOX_EXAGGERATION,
    DEFAULT_DIA_DEVICE,
    DEFAULT_DIA_GUIDANCE_SCALE,
    DEFAULT_DIA_MAX_NEW_TOKENS,
    DEFAULT_DIA_MODEL_CHECKPOINT,
    DEFAULT_DIA_SPEAKER_TAG,
    DEFAULT_DIA_TEMPERATURE,
    DEFAULT_DIA_TOP_K,
    DEFAULT_DIA_TOP_P,
    DEFAULT_F5_CFG_STRENGTH,
    DEFAULT_F5_CROSS_FADE_SECONDS,
    DEFAULT_F5_DEVICE,
    DEFAULT_F5_MODEL,
    DEFAULT_F5_NFE_STEP,
    DEFAULT_F5_SWAY_SAMPLING_COEF,
    DEFAULT_F5_TARGET_RMS,
    DEFAULT_LANGUAGE_CODE,
    DEFAULT_PROVIDER,
    DEFAULT_SAMPLE_RATE_HZ,
    DEFAULT_STYLE,
    KNOWN_PROVIDERS,
    PROVIDER_F5_TTS_LOCAL,
)


VoiceoverStatus = Literal["ok", "failed"]


class VoiceoverRun(BaseModel):
    run_id: str
    generated_at: str | None = None

    @field_validator("run_id")
    @classmethod
    def run_id_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run.run_id must not be empty")
        return value


class ChunkingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_max_chars: int | None = None
    max_sentences_per_chunk: int | None = None
    chunk_pause_seconds: float | None = None
    paragraph_pause_seconds: float | None = None

    @field_validator("chunk_max_chars", "max_sentences_per_chunk")
    @classmethod
    def optional_ints_must_be_positive(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("chunking integer overrides must be positive when provided")
        return value

    @field_validator("chunk_pause_seconds", "paragraph_pause_seconds")
    @classmethod
    def optional_pauses_must_be_non_negative(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError("chunking pause overrides must be non-negative when provided")
        return value


class AlignmentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require_script_beats: bool = True
    beat_pause_seconds: float = 0.08
    section_pause_seconds: float = 0.32

    @field_validator("beat_pause_seconds", "section_pause_seconds")
    @classmethod
    def pauses_must_be_non_negative(cls, value: float) -> float:
        if value < 0 or value > 2:
            raise ValueError("alignment pause values must be between 0 and 2 seconds")
        return value

class ChatterboxConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device: str = DEFAULT_CHATTERBOX_DEVICE
    exaggeration: float = DEFAULT_CHATTERBOX_EXAGGERATION
    cfg_weight: float = DEFAULT_CHATTERBOX_CFG_WEIGHT
    audio_prompt_path: str | None = None
    cache_dir: str | None = None

    @field_validator("device")
    @classmethod
    def device_must_be_supported(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in {"auto", "cpu", "mps", "cuda"}:
            raise ValueError("config.chatterbox.device must be one of auto, cpu, mps, or cuda")
        return cleaned

    @field_validator("exaggeration", "cfg_weight")
    @classmethod
    def generation_controls_must_be_non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("config.chatterbox exaggeration/cfg_weight values must be non-negative")
        return value

    @field_validator("audio_prompt_path", "cache_dir")
    @classmethod
    def optional_paths_must_not_be_empty(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("config.chatterbox optional paths must not be empty when provided")
        return value


class F5TTSConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = DEFAULT_F5_MODEL
    device: str = DEFAULT_F5_DEVICE
    ref_audio_path: str | None = None
    ref_text: str | None = None
    cache_dir: str | None = None
    nfe_step: int = DEFAULT_F5_NFE_STEP
    cfg_strength: float = DEFAULT_F5_CFG_STRENGTH
    sway_sampling_coef: float = DEFAULT_F5_SWAY_SAMPLING_COEF
    target_rms: float = DEFAULT_F5_TARGET_RMS
    cross_fade_duration: float = DEFAULT_F5_CROSS_FADE_SECONDS
    remove_silence: bool = False
    seed: int | None = None

    @field_validator("model", "device")
    @classmethod
    def required_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("config.f5_tts model/device values must not be empty")
        return value.strip()

    @field_validator("ref_audio_path", "ref_text", "cache_dir")
    @classmethod
    def optional_text_must_not_be_empty(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("config.f5_tts optional text/path values must not be empty when provided")
        return value

    @field_validator("nfe_step")
    @classmethod
    def nfe_step_must_be_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("config.f5_tts.nfe_step must be positive")
        return value

    @field_validator("cfg_strength", "target_rms")
    @classmethod
    def positive_floats_must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("config.f5_tts cfg_strength/target_rms values must be positive")
        return value

    @field_validator("cross_fade_duration")
    @classmethod
    def cross_fade_must_be_non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("config.f5_tts.cross_fade_duration must be non-negative")
        return value


class DiaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_checkpoint: str = DEFAULT_DIA_MODEL_CHECKPOINT
    device: str = DEFAULT_DIA_DEVICE
    cache_dir: str | None = None
    max_new_tokens: int = DEFAULT_DIA_MAX_NEW_TOKENS
    guidance_scale: float = DEFAULT_DIA_GUIDANCE_SCALE
    temperature: float = DEFAULT_DIA_TEMPERATURE
    top_p: float = DEFAULT_DIA_TOP_P
    top_k: int = DEFAULT_DIA_TOP_K
    speaker_tag: str = DEFAULT_DIA_SPEAKER_TAG

    @field_validator("model_checkpoint", "device", "speaker_tag")
    @classmethod
    def dia_text_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("config.dia text values must not be empty")
        return value.strip()

    @field_validator("cache_dir")
    @classmethod
    def dia_cache_dir_must_not_be_empty(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("config.dia.cache_dir must not be empty when provided")
        return value

    @field_validator("max_new_tokens", "top_k")
    @classmethod
    def dia_ints_must_be_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("config.dia max_new_tokens/top_k values must be positive")
        return value

    @field_validator("guidance_scale", "temperature", "top_p")
    @classmethod
    def dia_floats_must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("config.dia guidance_scale/temperature/top_p values must be positive")
        return value


class VoiceoverConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: str = DEFAULT_PROVIDER
    style: str = DEFAULT_STYLE
    voice: str | None = None
    speed: float | None = None
    language_code: str = DEFAULT_LANGUAGE_CODE
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ
    keep_chunks: bool = True
    force: bool = False
    output_dir: str
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    alignment: AlignmentConfig = Field(default_factory=AlignmentConfig)
    chatterbox: ChatterboxConfig = Field(default_factory=ChatterboxConfig)
    f5_tts: F5TTSConfig = Field(default_factory=F5TTSConfig)
    dia: DiaConfig = Field(default_factory=DiaConfig)

    @field_validator("provider")
    @classmethod
    def provider_must_be_known(cls, value: str) -> str:
        cleaned = value.strip()
        if cleaned not in KNOWN_PROVIDERS:
            known = ", ".join(sorted(KNOWN_PROVIDERS))
            raise ValueError(f"Unknown voiceover provider '{cleaned}'. Known providers: {known}")
        return cleaned

    @field_validator("style", "language_code", "output_dir")
    @classmethod
    def text_fields_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("config style, language_code, and output_dir must not be empty")
        return value

    @field_validator("sample_rate_hz")
    @classmethod
    def sample_rate_must_be_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("config.sample_rate_hz must be positive")
        return value

    @field_validator("speed")
    @classmethod
    def speed_must_be_positive_when_set(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("config.speed must be positive when provided")
        return value

    @model_validator(mode="after")
    def provider_specific_requirements(self) -> "VoiceoverConfig":
        if self.provider == PROVIDER_F5_TTS_LOCAL:
            if not self.f5_tts.ref_audio_path:
                raise ValueError("config.f5_tts.ref_audio_path is required for provider=f5_tts_local")
            if not self.f5_tts.ref_text:
                raise ValueError("config.f5_tts.ref_text is required for provider=f5_tts_local")
        return self


class ScriptGenerationData(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    generated_at: str | None = None
    selected_format: str | None = None
    script_package: dict[str, Any]


class ScriptGenerationEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str | None = None
    data: ScriptGenerationData
    summary: dict[str, Any] = Field(default_factory=dict)
    handoff: dict[str, Any] = Field(default_factory=dict)


class VoiceoverInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    script_generation: ScriptGenerationEnvelope | None = None
    script_text: str | None = None
    script_source: str | None = None

    @model_validator(mode="after")
    def exactly_one_script_source(self) -> "VoiceoverInput":
        has_script_generation = self.script_generation is not None
        has_script_text = self.script_text is not None and bool(self.script_text.strip())
        if has_script_generation == has_script_text:
            raise ValueError("input must provide exactly one of script_generation or non-empty script_text")
        return self


class VoiceoverRequest(BaseModel):
    run: VoiceoverRun
    config: VoiceoverConfig
    input: VoiceoverInput


class VoiceoverData(BaseModel):
    run_id: str
    generated_at: str
    voiceover_package: dict[str, Any]


class VoiceoverSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: str
    voice: str
    style: str
    audio_path: str
    duration_seconds: float
    chunk_count: int
    audio_unit_count: int = 0
    aligned_beat_count: int = 0
    word_count: int


class VoiceoverHandoff(BaseModel):
    ready_for_video_assembly: bool
    requires_manual_audio_review: bool


class VoiceoverResponse(BaseModel):
    status: VoiceoverStatus
    data: VoiceoverData
    summary: VoiceoverSummary
    handoff: VoiceoverHandoff
