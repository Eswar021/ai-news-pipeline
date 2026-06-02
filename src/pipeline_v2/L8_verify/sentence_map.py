from __future__ import annotations

import re

from src.pipeline.L1_collection.common import clean_text


SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def build_sentence_map(script_package: dict) -> list[dict]:
    sentences = []
    analysis_lookup = {
        section["section_id"]: {
            _normalize_sentence(value)
            for value in section.get("analysis_sentences", [])
            if clean_text(value)
        }
        for section in script_package.get("section_scripts", [])
    }

    for section in script_package.get("section_scripts", []):
        section_id = section["section_id"]
        section_sentences = _split_sentences(section.get("narration_text", ""))
        for index, sentence in enumerate(section_sentences, start=1):
            sentence_id = f"{section_id}_sent_{index:03d}"
            normalized = _normalize_sentence(sentence)
            used_fact_ids = _sentence_fact_ids(sentence, section)
            is_analysis = normalized in analysis_lookup.get(section_id, set())
            requires_support = (
                bool(clean_text(sentence))
                and (
                    (section.get("section_type") == "story" and not is_analysis)
                    or (section.get("section_type") != "story" and bool(used_fact_ids))
                )
            )
            sentences.append(
                {
                    "sentence_id": sentence_id,
                    "section_id": section_id,
                    "section_type": section.get("section_type", ""),
                    "section_order": section.get("section_order", 0),
                    "story_id": section.get("story_id", ""),
                    "sentence_index": index,
                    "sentence_text": sentence,
                    "used_fact_ids": used_fact_ids,
                    "required_fact_ids": list(section.get("required_fact_ids", [])),
                    "required_cautious_fact_ids": list(section.get("required_cautious_fact_ids", [])),
                    "is_analysis_sentence": is_analysis,
                    "requires_support_verification": requires_support,
                }
            )
    return sentences


def _split_sentences(text: str) -> list[str]:
    cleaned = clean_text(text)
    if not cleaned:
        return []
    return [part.strip() for part in SENTENCE_RE.split(cleaned) if part.strip()]


def _sentence_fact_ids(sentence: str, section: dict) -> list[str]:
    section_fact_ids = list(section.get("used_fact_ids", []))
    if not section_fact_ids:
        return []
    normalized_sentence = _normalize_sentence(sentence)
    matched = []
    for fact_id in section_fact_ids:
        if fact_id in normalized_sentence:
            matched.append(fact_id)
    # L7 narration should not speak fact IDs, so section-level fact use is the safest mapping.
    return matched or section_fact_ids


def _normalize_sentence(value: str) -> str:
    return clean_text(value).lower().strip("\"'“”‘’")
