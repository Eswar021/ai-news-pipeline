from __future__ import annotations

from dataclasses import dataclass


PROVIDER_KOKORO_LOCAL = "kokoro_local"
PROVIDER_CHATTERBOX_LOCAL = "chatterbox_local"
PROVIDER_F5_TTS_LOCAL = "f5_tts_local"
PROVIDER_DIA_TRANSFORMERS = "dia_transformers"
PROVIDER_OPENAI = "openai"
PROVIDER_GEMINI = "gemini"
PROVIDER_ELEVENLABS = "elevenlabs"

KNOWN_PROVIDERS = {
    PROVIDER_KOKORO_LOCAL,
    PROVIDER_CHATTERBOX_LOCAL,
    PROVIDER_F5_TTS_LOCAL,
    PROVIDER_DIA_TRANSFORMERS,
    PROVIDER_OPENAI,
    PROVIDER_GEMINI,
    PROVIDER_ELEVENLABS,
}
IMPLEMENTED_PROVIDERS = {
    PROVIDER_KOKORO_LOCAL,
    PROVIDER_CHATTERBOX_LOCAL,
    PROVIDER_F5_TTS_LOCAL,
    PROVIDER_DIA_TRANSFORMERS,
    PROVIDER_OPENAI,
    PROVIDER_GEMINI,
}

DEFAULT_PROVIDER = PROVIDER_KOKORO_LOCAL
DEFAULT_VOICE = "af_heart"
DEFAULT_LANGUAGE_CODE = "a"
DEFAULT_SPEED = 1.0
DEFAULT_SAMPLE_RATE_HZ = 24000
DEFAULT_KEEP_CHUNKS = True
DEFAULT_STYLE = "dramatic_news"
DEFAULT_CHUNK_MAX_CHARS = 850
DEFAULT_MAX_SENTENCES_PER_CHUNK = 2
DEFAULT_CHUNK_PAUSE_SECONDS = 0.16
DEFAULT_PARAGRAPH_PAUSE_SECONDS = 0.48
DEFAULT_CHATTERBOX_DEVICE = "auto"
DEFAULT_CHATTERBOX_EXAGGERATION = 0.65
DEFAULT_CHATTERBOX_CFG_WEIGHT = 0.5
DEFAULT_F5_MODEL = "F5TTS_v1_Base"
DEFAULT_F5_DEVICE = "auto"
DEFAULT_F5_NFE_STEP = 32
DEFAULT_F5_CFG_STRENGTH = 2.0
DEFAULT_F5_SWAY_SAMPLING_COEF = -1.0
DEFAULT_F5_TARGET_RMS = 0.1
DEFAULT_F5_CROSS_FADE_SECONDS = 0.15
DEFAULT_DIA_MODEL_CHECKPOINT = "nari-labs/Dia-1.6B-0626"
DEFAULT_DIA_DEVICE = "auto"
DEFAULT_DIA_MAX_NEW_TOKENS = 512
DEFAULT_DIA_GUIDANCE_SCALE = 3.0
DEFAULT_DIA_TEMPERATURE = 1.8
DEFAULT_DIA_TOP_P = 0.9
DEFAULT_DIA_TOP_K = 45
DEFAULT_DIA_SPEAKER_TAG = "S1"
DEFAULT_OPENAI_TTS_MODEL = "gpt-4o-mini-tts"
DEFAULT_OPENAI_TTS_VOICE = "cedar"
DEFAULT_GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"
DEFAULT_GEMINI_TTS_VOICE = "Kore"
DEFAULT_API_TTS_WORKER_COUNT = 3
DEFAULT_API_TTS_REQUEST_TIMEOUT_SECONDS = 180.0
DEFAULT_API_TTS_MAX_RETRIES = 3
DEFAULT_API_TTS_RETRY_INITIAL_DELAY_SECONDS = 1.0
DEFAULT_API_TTS_RETRY_MAX_DELAY_SECONDS = 8.0
DEFAULT_MASTERING_TARGET_LUFS = -16.0
DEFAULT_MASTERING_TRUE_PEAK_DB = -1.0
DEFAULT_MASTERING_LOUDNESS_RANGE_LU = 7.0
DEFAULT_MASTERING_DURATION_TOLERANCE_SECONDS = 0.08
DEFAULT_CAPTION_MAX_CHARS = 48
DEFAULT_CAPTION_MAX_WORDS = 12
DEFAULT_CAPTION_MIN_SECONDS = 0.8


@dataclass(frozen=True)
class VoiceoverStyle:
    name: str
    description: str
    default_voice: str
    speed: float
    chunk_max_chars: int
    max_sentences_per_chunk: int
    chunk_pause_seconds: float
    paragraph_pause_seconds: float


VOICEOVER_STYLES: dict[str, VoiceoverStyle] = {
    "warm_explainer": VoiceoverStyle(
        name="warm_explainer",
        description="Friendly, relaxed, clear explainer cadence.",
        default_voice="af_heart",
        speed=0.96,
        chunk_max_chars=620,
        max_sentences_per_chunk=2,
        chunk_pause_seconds=0.2,
        paragraph_pause_seconds=0.55,
    ),
    "general_youtube": VoiceoverStyle(
        name="general_youtube",
        description="Plain-English YouTube narration with more forward momentum.",
        default_voice="af_bella",
        speed=1.04,
        chunk_max_chars=560,
        max_sentences_per_chunk=2,
        chunk_pause_seconds=0.16,
        paragraph_pause_seconds=0.46,
    ),
    "dramatic_news": VoiceoverStyle(
        name="dramatic_news",
        description="Punchier news style with shorter chunks and stronger pauses.",
        default_voice="af_bella",
        speed=1.02,
        chunk_max_chars=420,
        max_sentences_per_chunk=1,
        chunk_pause_seconds=0.22,
        paragraph_pause_seconds=0.65,
    ),
    "calm_documentary": VoiceoverStyle(
        name="calm_documentary",
        description="Steadier documentary cadence for longer, less hype-driven videos.",
        default_voice="af_nicole",
        speed=0.92,
        chunk_max_chars=700,
        max_sentences_per_chunk=2,
        chunk_pause_seconds=0.24,
        paragraph_pause_seconds=0.6,
    ),
}


def validate_provider(provider: str) -> None:
    if provider not in KNOWN_PROVIDERS:
        known = ", ".join(sorted(KNOWN_PROVIDERS))
        raise ValueError(f"Unknown voiceover provider '{provider}'. Known providers: {known}")
    if provider not in IMPLEMENTED_PROVIDERS:
        raise NotImplementedError(f"Voiceover provider '{provider}' is not implemented yet.")


def resolve_style(style_name: str) -> VoiceoverStyle:
    if style_name not in VOICEOVER_STYLES:
        known = ", ".join(sorted(VOICEOVER_STYLES))
        raise ValueError(f"Unknown voiceover style '{style_name}'. Known styles: {known}")
    return VOICEOVER_STYLES[style_name]
