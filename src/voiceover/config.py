from __future__ import annotations

from dataclasses import dataclass


PROVIDER_KOKORO_LOCAL = "kokoro_local"
PROVIDER_OPENAI = "openai"
PROVIDER_ELEVENLABS = "elevenlabs"

KNOWN_PROVIDERS = {PROVIDER_KOKORO_LOCAL, PROVIDER_OPENAI, PROVIDER_ELEVENLABS}
IMPLEMENTED_PROVIDERS = {PROVIDER_KOKORO_LOCAL}

DEFAULT_PROVIDER = PROVIDER_KOKORO_LOCAL
DEFAULT_VOICE = "af_heart"
DEFAULT_LANGUAGE_CODE = "a"
DEFAULT_SPEED = 1.0
DEFAULT_SAMPLE_RATE_HZ = 24000
DEFAULT_CHUNK_MAX_CHARS = 850
DEFAULT_KEEP_CHUNKS = True
DEFAULT_STYLE = "general_youtube"
DEFAULT_MAX_SENTENCES_PER_CHUNK = 2
DEFAULT_CHUNK_PAUSE_SECONDS = 0.16
DEFAULT_PARAGRAPH_PAUSE_SECONDS = 0.48

DEFAULT_AUDITION_VOICES = [
    "af_heart",
    "af_bella",
    "af_nicole",
    "af_jessica",
    "am_puck",
    "bm_george",
]
DEFAULT_AUDITION_TEXT = (
    "AI news moves fast, but not every launch deserves your attention. "
    "Today, we are looking at what changed, why it matters, and what to watch next. "
    "The big question is simple: is this useful right now, or is it just another impressive demo?"
)


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


@dataclass(frozen=True)
class VoiceoverConfig:
    provider: str = DEFAULT_PROVIDER
    voice: str = DEFAULT_VOICE
    style: str = DEFAULT_STYLE
    language_code: str = DEFAULT_LANGUAGE_CODE
    speed: float = DEFAULT_SPEED
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ
    chunk_max_chars: int = DEFAULT_CHUNK_MAX_CHARS
    max_sentences_per_chunk: int = DEFAULT_MAX_SENTENCES_PER_CHUNK
    chunk_pause_seconds: float = DEFAULT_CHUNK_PAUSE_SECONDS
    paragraph_pause_seconds: float = DEFAULT_PARAGRAPH_PAUSE_SECONDS
    keep_chunks: bool = DEFAULT_KEEP_CHUNKS


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
