from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import re

from src.llm.client import OpenAIJSONClient
from src.pipeline.L1_collection.common import clean_text


MAX_SECTION_WRITE_ATTEMPTS = 3
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
WATCH_ONLY_BLOCKED_PHRASES = (
    "start validating",
    "validate in",
    "deploy this",
    "deploy it",
    "deploy now",
    "start deploying",
    "put into production",
    "production rollout",
    "integrate this",
    "integrate it",
    "start integrating",
    "change your workflow",
    "change workflows",
    "change your",
    "use it today",
    "start using",
)
CAUTIOUS_QUALIFIERS = (
    "according to",
    "reported",
    "reports",
    "the paper",
    "the authors",
    "the source",
    "the study",
    "appears",
    "may",
    "could",
    "suggests",
)
FIRST_PERSON_SOURCE_PHRASES = (
    "we release",
    "we introduce",
    "we present",
    "we propose",
    "our paper",
    "our method",
    "our benchmark",
    "our framework",
)
UNSUPPORTED_PERFORMANCE_PHRASES = (
    "without sacrificing accuracy",
    "without compromising accuracy",
    "with no accuracy loss",
    "zero accuracy loss",
    "guaranteed performance",
    "guaranteed improvements",
)


def write_sections(
    sections: list[dict],
    *,
    manifest: dict,
    layer7_cfg: dict,
    prompt_bundle: dict,
    log_path: Path,
) -> list[dict]:
    worker_count = int(layer7_cfg["script_worker_count"])
    if worker_count < 1:
        raise ValueError("layer_7.script_worker_count must be at least 1")

    if worker_count == 1:
        return [
            _write_section(
                section,
                manifest=manifest,
                layer7_cfg=layer7_cfg,
                prompt_bundle=prompt_bundle,
                log_path=log_path,
            )
            for section in sections
        ]

    ordered: list[dict | None] = [None] * len(sections)
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_index = {
            executor.submit(
                _write_section,
                section,
                manifest=manifest,
                layer7_cfg=layer7_cfg,
                prompt_bundle=prompt_bundle,
                log_path=log_path,
            ): index
            for index, section in enumerate(sections)
        }
        for future in as_completed(future_to_index):
            result = future.result()
            ordered[future_to_index[future]] = result
            print(
                f"[L7] Section done — {result['section_id']} "
                f"words={result['word_count']} facts={len(result['used_fact_ids'])}"
            )

    if any(result is None for result in ordered):
        raise RuntimeError("L7 section writing finished with missing outputs")
    return [result for result in ordered if result is not None]


def _write_section(
    section: dict,
    *,
    manifest: dict,
    layer7_cfg: dict,
    prompt_bundle: dict,
    log_path: Path,
) -> dict:
    client = OpenAIJSONClient(model=layer7_cfg["script_writer_model"])
    last_result: dict | None = None
    for attempt in range(1, MAX_SECTION_WRITE_ATTEMPTS + 1):
        response = client.generate_json(
            module_name="roundup_script_writer",
            system_prompt=prompt_bundle["system"],
            user_prompt=_build_user_prompt(
                section,
                manifest,
                prompt_bundle,
                retry_feedback=_retry_feedback(last_result) if last_result else "",
            ),
            log_path=log_path,
            metadata={
                "section_id": section["section_id"],
                "section_type": section["section_type"],
                "story_id": section.get("story_id", ""),
                "attempt": attempt,
            },
        )
        result = _validate_section_response(response, section, layer7_cfg)
        rewrite_reasons = _rewrite_reasons(result, section)
        if not rewrite_reasons:
            return result
        result["rewrite_reasons"] = rewrite_reasons
        last_result = result
        if attempt < MAX_SECTION_WRITE_ATTEMPTS:
            print(
                f"[L7] Retrying section — {section['section_id']} "
                f"reason={'; '.join(rewrite_reasons)}"
            )

    if last_result:
        raise ValueError(
            f"{section['section_id']} failed section quality checks after rewrite: "
            f"{last_result.get('rewrite_reasons', [])}"
        )
    raise RuntimeError(f"L7 failed to write section: {section['section_id']}")


def _build_user_prompt(
    section: dict,
    manifest: dict,
    prompt_bundle: dict,
    *,
    retry_feedback: str = "",
) -> str:
    channel = manifest["layer_0"]["channel"]
    payload = {
        "channel_name": channel["channel_name"],
        "content_promise": channel.get("content_promise", ""),
        "allowed_topics": channel.get("allowed_topics", []),
        "section": section,
        "required_json_schema": {
            "narration_text": "natural spoken narration only, no visual/editor notes",
            "used_fact_ids": "list of fact IDs used in the narration",
            "analysis_sentences": "list of sentence strings from narration that are editorial analysis, not source facts",
        },
    }
    preamble = prompt_bundle.get("user_preamble", "")
    section_rule = _section_rule(section)
    length_rule = (
        f"Length rule: write at least {section.get('minimum_word_count', 0)} words "
        f"and aim close to {section['word_budget']} words. "
        "Do not underwrite the section; this is a real video segment, not a short summary."
    )
    analysis_rule = (
        "ANALYSIS ALLOWED = yes. You may add brief synthesis only when it follows directly from the "
        "provided facts, viewer-value context, or section goal. Do not add new entities, new numbers, "
        "new mechanisms, or predictions."
        if section.get("analysis_allowed")
        else "ANALYSIS ALLOWED = no. Use only direct factual narration from the provided facts."
    )
    return (
        f"{preamble}\n\n" if preamble else ""
    ) + (
        "Write this single section of an AI news roundup script.\n"
        f"{section_rule}\n"
        f"{length_rule}\n"
        f"{analysis_rule}\n"
        f"{retry_feedback}"
        "Return JSON with exactly these keys: narration_text, used_fact_ids, analysis_sentences.\n"
        "Use the exact fact_id strings when a fact appears in narration.\n"
        "Do not mention fact IDs aloud in the narration.\n"
        "Treat section/story/chapter titles as context, not factual evidence; only fact_text values are evidence.\n"
        "Follow section.takeaway_rule exactly when present.\n"
        "Do not include visual directions, lower thirds, editor notes, markdown, or headings in narration_text.\n\n"
        f"Section payload:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _section_rule(section: dict) -> str:
    section_type = section["section_type"]
    if section_type == "story":
        required = section.get("required_fact_ids", [])
        cautious = section.get("required_cautious_fact_ids", [])
        return (
            f"Story-section rule: you must use every required_fact_id: {required}. "
            f"Required cautious fact IDs need qualifying language: {cautious}. "
            "Optional facts may be used only if they improve clarity and fit the word budget. "
            "Start from the viewer-facing change, not with 'today we cover' or 'this section'. "
            "End with one takeaway or caveat that follows from fact_text, not generic advice."
        )
    if section_type == "intro":
        return (
            "Intro rule: preview the episode promise and direction. Do not introduce source-specific facts, "
            "numbers, or claims that belong inside story sections. Open with a concrete tension or question, "
            "not with a generic channel description."
        )
    if section_type == "closing":
        return (
            "Closing rule: synthesize the episode theme without adding new facts, new numbers, or new named claims. "
            "Use a natural signoff instead of a dry report ending."
        )
    raise ValueError(f"Unsupported L7 section type: {section_type}")


def _validate_section_response(response: dict, section: dict, layer7_cfg: dict) -> dict:
    narration = _polish_narration(clean_text(response.get("narration_text", "")), section)
    if not narration:
        raise ValueError(f"roundup_script_writer response missing narration_text for {section['section_id']}")

    used_fact_ids = response.get("used_fact_ids", [])
    if not isinstance(used_fact_ids, list):
        raise ValueError(f"roundup_script_writer used_fact_ids must be a list for {section['section_id']}")
    used_fact_ids = _dedupe([clean_text(value) for value in used_fact_ids if clean_text(value)])

    known_fact_ids = {fact["fact_id"] for fact in section.get("facts", [])}
    unknown_used = [fact_id for fact_id in used_fact_ids if fact_id not in known_fact_ids]
    if unknown_used:
        raise ValueError(
            f"roundup_script_writer used unknown fact_id(s) for {section['section_id']}: {unknown_used}"
        )

    required_fact_ids = list(section.get("required_fact_ids", []))
    omitted_required = [fact_id for fact_id in required_fact_ids if fact_id not in used_fact_ids]
    if section["section_type"] == "story" and omitted_required:
        raise ValueError(
            f"roundup_script_writer omitted required fact_id(s) for "
            f"{section['section_id']}: {omitted_required}"
        )

    analysis_sentences = response.get("analysis_sentences", [])
    if not isinstance(analysis_sentences, list):
        raise ValueError(f"roundup_script_writer analysis_sentences must be a list for {section['section_id']}")

    word_count = _word_count(narration)
    estimated_seconds = round(word_count / int(layer7_cfg["words_per_minute"]) * 60, 1)
    return {
        "section_id": section["section_id"],
        "section_type": section["section_type"],
        "section_order": section["section_order"],
        "story_id": section.get("story_id", ""),
        "title": section["title"],
        "chapter_title": section.get("chapter_title", section["title"]),
        "role": section.get("role", ""),
        "target_seconds": section["target_seconds"],
        "word_budget": section["word_budget"],
        "minimum_word_count": section.get("minimum_word_count", 0),
        "word_count": word_count,
        "estimated_seconds": estimated_seconds,
        "narration_text": narration,
        "used_fact_ids": used_fact_ids,
        "required_fact_ids": required_fact_ids,
        "required_cautious_fact_ids": list(section.get("required_cautious_fact_ids", [])),
        "optional_fact_ids": list(section.get("optional_fact_ids", [])),
        "available_fact_ids": _dedupe(required_fact_ids + list(section.get("optional_fact_ids", []))),
        "omitted_required_fact_ids": omitted_required,
        "analysis_sentences": _validated_analysis_sentences(narration, analysis_sentences),
        "caution_notes": list(section.get("caution_notes", [])),
        "visual_notes": list(section.get("visual_notes", [])),
    }


def _rewrite_reasons(result: dict, section: dict) -> list[str]:
    reasons = []
    if (
        result.get("section_type") == "story"
        and int(result.get("minimum_word_count", 0) or 0) > 0
        and int(result.get("word_count", 0) or 0) < int(result.get("minimum_word_count", 0) or 0)
    ):
        reasons.append(
            f"too short: {result['word_count']} words, minimum {result['minimum_word_count']}"
        )
    blocked_phrases = _watch_only_blocked_phrases(result, section)
    if blocked_phrases:
        reasons.append(f"watch-only section used unsupported action language: {blocked_phrases}")
    repeated_sentences = _repeated_sentence_markers(result.get("narration_text", ""))
    if repeated_sentences:
        reasons.append(f"repeated narration sentence or idea: {repeated_sentences}")
    repeated_phrases = _repeated_key_phrases(result.get("narration_text", ""))
    if repeated_phrases:
        reasons.append(f"repeated key phrasing: {repeated_phrases}")
    first_person_source = _first_person_source_phrases(result.get("narration_text", ""), section)
    if first_person_source:
        reasons.append(f"first-person source voice in narration: {first_person_source}")
    if _caution_section_missing_qualifier(result.get("narration_text", ""), section):
        reasons.append("caution-only section missing source attribution or qualifier language")
    unsupported_performance = _unsupported_performance_phrases(result.get("narration_text", ""), section)
    if unsupported_performance:
        reasons.append(f"unsupported performance qualifier: {unsupported_performance}")
    return reasons


def _retry_feedback(result: dict | None) -> str:
    if not result:
        return ""
    rewrite_reasons = result.get("rewrite_reasons", [])
    reason_text = "; ".join(rewrite_reasons) if rewrite_reasons else "the previous draft needs revision"
    return (
        f"Revision note: {reason_text}. "
        "Rewrite the section with useful spoken explanation, not filler. "
        "Use every required fact again, add optional facts only when they improve clarity, "
        "follow section.takeaway_rule exactly, and keep the same evidence and cautious-language rules.\n"
    )


def _watch_only_blocked_phrases(result: dict, section: dict) -> list[str]:
    if section.get("evidence_mode") not in {"caution_only", "research_watch", "limited_release"}:
        return []
    lower = clean_text(result.get("narration_text", "")).lower()
    return [phrase for phrase in WATCH_ONLY_BLOCKED_PHRASES if phrase in lower]


def _validated_analysis_sentences(narration: str, values: list) -> list[str]:
    if not isinstance(values, list):
        return []
    narration_lookup = {_normalize_sentence(sentence): sentence for sentence in _split_sentences(narration)}
    kept = []
    for value in values:
        cleaned = clean_text(value)
        if not cleaned:
            continue
        normalized = _normalize_sentence(cleaned)
        if normalized in narration_lookup:
            kept.append(narration_lookup[normalized])
    return _dedupe(kept)


def _polish_narration(narration: str, section: dict) -> str:
    if not narration:
        return narration
    replacements = {
        "Report notes the release": "The paper notes the release",
        "report notes the release": "the paper notes the release",
        "Change is here: ": "",
        "change is here: ": "",
        "To push transparency, we release": "The paper says the authors release",
        "to push transparency, we release": "the paper says the authors release",
        "We release the agentic tool": "The authors say they release the agentic tool",
        "we release the agentic tool": "the authors say they release the agentic tool",
        "ABA marks a shift in how we judge benchmarks:": "The paper presents ABA as a benchmark-auditing approach:",
        "aba marks a shift in how we judge benchmarks:": "the paper presents ABA as a benchmark-auditing approach:",
        "What to watch next: monitor audit impact on benchmark reliability, with source attribution.": "",
        "what to watch next: monitor audit impact on benchmark reliability, with source attribution.": "",
    }
    polished = narration
    for old, new in replacements.items():
        polished = polished.replace(old, new)

    if section.get("section_type") == "story":
        title = clean_text(section.get("title", ""))
        prefix = f"{title}. {title}. "
        if title and polished.startswith(prefix):
            polished = f"{title}. {polished[len(prefix):]}"
    return clean_text(polished)


def _repeated_sentence_markers(text: str) -> list[str]:
    sentences = [_normalize_sentence(sentence) for sentence in _split_sentences(text)]
    seen = set()
    repeated = []
    for sentence in sentences:
        if len(sentence.split()) < 7:
            continue
        if sentence in seen:
            repeated.append(sentence[:90])
        seen.add(sentence)
    return repeated[:3]


def _repeated_key_phrases(text: str) -> list[str]:
    normalized = _normalize_sentence(text)
    phrases = [
        "structured summaries",
        "surface relevant clinical details",
        "draft initial rationales",
        "production-ready retrieval-augmented generation",
        "traditional ten blue links",
    ]
    repeated = [phrase for phrase in phrases if normalized.count(phrase) > 1]
    return repeated[:3]


def _first_person_source_phrases(text: str, section: dict) -> list[str]:
    if section.get("section_type") != "story":
        return []
    normalized = _normalize_sentence(text)
    return [phrase for phrase in FIRST_PERSON_SOURCE_PHRASES if phrase in normalized]


def _caution_section_missing_qualifier(text: str, section: dict) -> bool:
    if not section.get("required_cautious_fact_ids"):
        return False
    normalized = _normalize_sentence(text)
    return not any(qualifier in normalized for qualifier in CAUTIOUS_QUALIFIERS)


def _unsupported_performance_phrases(text: str, section: dict) -> list[str]:
    if section.get("section_type") != "story":
        return []
    narration = _normalize_sentence(text)
    fact_text = _normalize_sentence(
        " ".join(clean_text(fact.get("fact_text", "")) for fact in section.get("facts", []))
    )
    return [
        phrase
        for phrase in UNSUPPORTED_PERFORMANCE_PHRASES
        if phrase in narration and phrase not in fact_text
    ]


def _split_sentences(text: str) -> list[str]:
    cleaned = clean_text(text)
    if not cleaned:
        return []
    return [part.strip() for part in SENTENCE_RE.split(cleaned) if part.strip()]


def _normalize_sentence(value: str) -> str:
    return clean_text(value).lower().strip("\"'“”‘’")


def _word_count(text: str) -> int:
    return len([part for part in text.split() if part.strip()])


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    kept = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        kept.append(value)
    return kept
