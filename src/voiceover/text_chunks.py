from __future__ import annotations

import re


SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")
WHITESPACE_RE = re.compile(r"\s+")
WORD_RE = re.compile(r"\b[\w'-]+\b")


def split_narration_into_chunks(
    text: str,
    *,
    max_chars: int,
    max_sentences_per_chunk: int = 2,
    chunk_pause_seconds: float = 0.16,
    paragraph_pause_seconds: float = 0.48,
) -> list[dict]:
    cleaned = clean_text(text)
    if not cleaned:
        return []

    chunks: list[dict] = []
    current_sentences: list[str] = []
    current_paragraph_index = 0
    paragraphs = _paragraphs(cleaned)
    for paragraph_index, paragraph in enumerate(paragraphs, start=1):
        for sentence in _sentence_parts(paragraph, max_chars=max_chars):
            if not sentence:
                continue
            candidate_sentences = current_sentences + [sentence]
            candidate = " ".join(candidate_sentences).strip()
            sentence_limit_hit = len(candidate_sentences) > max_sentences_per_chunk
            char_limit_hit = len(candidate) > max_chars
            if current_sentences and (sentence_limit_hit or char_limit_hit):
                chunks.append(
                    _chunk_payload(
                        current_sentences,
                        paragraph_index=current_paragraph_index,
                        pause_after_seconds=chunk_pause_seconds,
                        prosody_reason="sentence_group",
                    )
                )
                current_sentences = [sentence]
                current_paragraph_index = paragraph_index
            else:
                if not current_sentences:
                    current_paragraph_index = paragraph_index
                current_sentences = candidate_sentences

        if current_sentences:
            is_last_paragraph = paragraph_index == len(paragraphs)
            chunks.append(
                _chunk_payload(
                    current_sentences,
                    paragraph_index=current_paragraph_index,
                    pause_after_seconds=0.0 if is_last_paragraph else paragraph_pause_seconds,
                    prosody_reason="paragraph_break" if not is_last_paragraph else "script_end",
                )
            )
            current_sentences = []

    return [
        {
            "chunk_id": f"chunk_{index:03d}",
            "order": index,
            **chunk,
        }
        for index, chunk in enumerate(chunks, start=1)
    ]


def clean_text(text: str) -> str:
    paragraphs = [WHITESPACE_RE.sub(" ", line).strip() for line in text.splitlines()]
    return "\n\n".join(line for line in paragraphs if line).strip()


def word_count(text: str) -> int:
    return len(WORD_RE.findall(text))


def estimated_seconds_from_words(words: int, *, words_per_minute: int = 145) -> float:
    if words <= 0:
        return 0.0
    return round((words / words_per_minute) * 60, 1)


def _paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]


def _sentence_parts(paragraph: str, *, max_chars: int) -> list[str]:
    sentences = [part.strip() for part in SENTENCE_BOUNDARY_RE.split(paragraph) if part.strip()]
    parts: list[str] = []
    for sentence in sentences:
        if len(sentence) <= max_chars:
            parts.append(sentence)
            continue
        parts.extend(_split_long_sentence(sentence, max_chars=max_chars))
    return parts


def _split_long_sentence(sentence: str, *, max_chars: int) -> list[str]:
    words = sentence.split()
    parts: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join(current + [word])
        if current and len(candidate) > max_chars:
            parts.append(" ".join(current).strip())
            current = [word]
        else:
            current.append(word)
    if current:
        parts.append(" ".join(current).strip())
    return parts


def _chunk_payload(
    sentences: list[str],
    *,
    paragraph_index: int,
    pause_after_seconds: float,
    prosody_reason: str,
) -> dict:
    text = " ".join(sentences).strip()
    return {
        "text": text,
        "word_count": word_count(text),
        "char_count": len(text),
        "sentence_count": len(sentences),
        "paragraph_index": paragraph_index,
        "pause_after_seconds": round(pause_after_seconds, 2),
        "prosody_reason": prosody_reason,
    }
