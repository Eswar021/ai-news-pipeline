from __future__ import annotations

from src.pipeline.L1_collection.common import clean_text


def build_roundup_sections(content_packet: dict, layer7_cfg: dict) -> list[dict]:
    words_per_minute = int(layer7_cfg["words_per_minute"])
    video = content_packet["video"]
    segments = content_packet["segment_plan"]
    sections = [
        _intro_section(video, segments, words_per_minute),
    ]

    for index, segment in enumerate(segments):
        previous_segment = segments[index - 1] if index > 0 else None
        next_segment = segments[index + 1] if index + 1 < len(segments) else None
        sections.append(
            _story_section(
                segment,
                video,
                words_per_minute,
                previous_segment=previous_segment,
                next_segment=next_segment,
            )
        )

    sections.append(_closing_section(video, segments, words_per_minute))
    return sections


def _intro_section(video: dict, segments: list[dict], words_per_minute: int) -> dict:
    titles = [segment["story_title"] for segment in segments]
    target_seconds = int(video.get("intro_seconds", 35))
    lead_title = segments[0]["story_title"] if segments else ""
    supporting_titles = [segment["story_title"] for segment in segments[1:]]
    return {
        "section_id": "section_00_intro",
        "section_type": "intro",
        "section_order": 0,
        "title": "Intro",
        "analysis_allowed": True,
        "target_seconds": target_seconds,
        "word_budget": _word_budget(target_seconds, words_per_minute),
        "minimum_word_count": _minimum_words(target_seconds, words_per_minute),
        "required_fact_ids": [],
        "required_cautious_fact_ids": [],
        "optional_fact_ids": [],
        "facts": [],
        "caution_notes": [],
        "visual_notes": [
            "Use a concise title card and quick source/logo montage. Do not put visual directions in narration.",
        ],
        "writing_context": {
            "viewer_promise": video.get("viewer_promise", ""),
            "opening_hook_direction": video.get("opening_hook_direction", ""),
            "thesis_or_theme": video.get("thesis_or_theme", ""),
            "tone": video.get("tone", ""),
            "lead_story_title": lead_title,
            "supporting_story_titles": supporting_titles,
            "segment_titles": titles,
            "section_goal": (
                "Open with a concrete viewer-facing tension, preview the lead and the episode's story mix, "
                "then promise practical takeaways without mechanically listing every story or sounding like a report abstract."
            ),
        },
    }


def _story_section(
    segment: dict,
    video: dict,
    words_per_minute: int,
    *,
    previous_segment: dict | None,
    next_segment: dict | None,
) -> dict:
    target_seconds = int(segment["target_seconds"])
    required_facts = list(segment.get("required_facts", []))
    optional_facts = list(segment.get("optional_facts", []))
    evidence_mode = _evidence_mode(segment, required_facts, optional_facts)
    return {
        "section_id": f"section_{segment['segment_order']:02d}_{segment['story_id']}",
        "section_type": "story",
        "section_order": int(segment["segment_order"]),
        "story_id": segment["story_id"],
        "title": segment["story_title"],
        "chapter_title": _chapter_title(segment),
        "role": segment["role"],
        "analysis_allowed": True,
        "target_seconds": target_seconds,
        "word_budget": _word_budget(target_seconds, words_per_minute),
        "minimum_word_count": _minimum_words(target_seconds, words_per_minute),
        "required_fact_ids": list(segment.get("required_fact_ids", [])),
        "required_cautious_fact_ids": list(segment.get("required_cautious_fact_ids", [])),
        "optional_fact_ids": list(segment.get("optional_fact_ids", [])),
        "facts": _compact_facts(required_facts + optional_facts),
        "required_facts": _compact_facts(required_facts),
        "optional_facts": _compact_facts(optional_facts),
        "caution_notes": list(segment.get("caution_notes", [])),
        "evidence_mode": evidence_mode,
        "takeaway_rule": _takeaway_rule(evidence_mode),
        "visual_notes": _story_visual_notes(segment),
        "writing_context": {
            "viewer_promise": segment.get("viewer_value", {}).get("viewer_promise", ""),
            "primary_viewer_question": segment.get("viewer_value", {}).get("primary_viewer_question", ""),
            "why_this_story_now": segment.get("viewer_value", {}).get("why_this_story_now", ""),
            "guidance": segment.get("guidance", ""),
            "story_identity": segment.get("story_identity", {}),
            "episode_theme": video.get("thesis_or_theme", ""),
            "tone": video.get("tone", ""),
            "blocked_angles": list(video.get("blocked_angles", []))[:12],
            "transition_from": previous_segment.get("story_title", "") if previous_segment else "",
            "transition_to": next_segment.get("story_title", "") if next_segment else "",
            "section_goal": _section_goal(segment, evidence_mode),
        },
    }


def _closing_section(video: dict, segments: list[dict], words_per_minute: int) -> dict:
    target_seconds = int(video.get("closing_seconds", 20))
    return {
        "section_id": "section_99_closing",
        "section_type": "closing",
        "section_order": len(segments) + 1,
        "title": "Closing",
        "analysis_allowed": True,
        "target_seconds": target_seconds,
        "word_budget": _word_budget(target_seconds, words_per_minute),
        "minimum_word_count": _minimum_words(target_seconds, words_per_minute),
        "required_fact_ids": [],
        "required_cautious_fact_ids": [],
        "optional_fact_ids": [],
        "facts": [],
        "caution_notes": [],
        "visual_notes": [
            "Use a clean recap card with the episode theme and source reminder. Do not put visual directions in narration.",
        ],
        "writing_context": {
            "viewer_promise": video.get("viewer_promise", ""),
            "thesis_or_theme": video.get("thesis_or_theme", ""),
            "editorial_angle": video.get("editorial_angle", ""),
            "tone": video.get("tone", ""),
            "covered_titles": [segment["story_title"] for segment in segments],
            "section_goal": (
                "Land the episode theme in plain language, remind viewers what to watch next, "
                "and end with a short natural signoff."
            ),
        },
    }


def _compact_facts(facts: list[dict]) -> list[dict]:
    compact = []
    for fact in facts:
        support_records = []
        for support in fact.get("support_records", [])[:3]:
            support_records.append(
                {
                    "record_key": support.get("record_key", ""),
                    "source_name": support.get("source_name", ""),
                    "source_url": support.get("source_url", ""),
                    "source_group": support.get("source_group", ""),
                    "trust_tier": support.get("trust_tier", ""),
                    "support_level": support.get("support_level", ""),
                }
            )
        compact.append(
            {
                "fact_id": fact["fact_id"],
                "fact_text": clean_text(fact.get("fact_text", "")),
                "fact_type": fact.get("fact_type", ""),
                "status": fact.get("status", ""),
                "confidence": fact.get("confidence", ""),
                "usefulness_score": fact.get("usefulness_score", 0),
                "support_records": support_records,
            }
        )
    return compact


def _story_visual_notes(segment: dict) -> list[str]:
    source_names = []
    for record in segment.get("selected_supporting_records", [])[:3]:
        name = clean_text(record.get("source_name", record.get("source", "")))
        if name and name not in source_names:
            source_names.append(name)
    source_hint = ", ".join(source_names) if source_names else "supporting sources"
    return [
        f"Show the story title and source card for {source_hint}.",
        "Use one short evidence callout for a required fact; do not add claims not present in the packet.",
    ]


def _chapter_title(segment: dict) -> str:
    title = clean_text(segment.get("story_title", ""))
    identity = segment.get("story_identity", {})
    product = clean_text(identity.get("product_or_project", ""))
    story_type = clean_text(identity.get("story_type", ""))
    if _is_known_identity(product) and (len(title) > 48 or story_type == "research_result"):
        return _shorten_title(_pretty_identity(product), 64)
    if len(title) <= 64:
        return title
    entity = clean_text(identity.get("owning_org", "")) or clean_text(identity.get("primary_entity", ""))
    action = clean_text(identity.get("story_action", ""))
    if story_type == "research_result" and _is_known_identity(entity):
        return f"{_pretty_identity(entity)} research result"
    if _is_known_identity(entity) and _is_useful_action(action):
        return f"{_pretty_identity(entity)}: {_pretty_identity(action)}"
    return _shorten_title(title, 64)


def _section_goal(segment: dict, evidence_mode: str) -> str:
    if evidence_mode in {"caution_only", "research_watch", "limited_release"}:
        return (
            "Keep this as a watch item: explain what the source claims, why it is interesting, "
            "and what evidence is still needed. Do not turn it into deployment or integration advice."
        )
    role = segment.get("role", "")
    if role == "lead":
        return (
            "Make the story feel worth leading with: start from the practical problem, explain what changed, "
            "then give the builder/operator takeaway and caveat."
        )
    if role == "major":
        return (
            "Give a clear mini-arc: what changed, why it matters now, what guardrail or verification point "
            "the viewer should remember."
        )
    return (
        "Keep it tight: one memorable change, one reason it matters, and one practical caveat or takeaway."
    )


def _evidence_mode(segment: dict, required_facts: list[dict], optional_facts: list[dict]) -> str:
    facts = required_facts + optional_facts
    statuses = {clean_text(fact.get("status", "")).lower() for fact in facts}
    fact_text = " ".join(clean_text(fact.get("fact_text", "")).lower() for fact in facts)
    source_groups = {clean_text(value).lower() for value in segment.get("source_groups", [])}
    story_type = clean_text(segment.get("story_identity", {}).get("story_type", "")).lower()
    if facts and statuses <= {"cautious"}:
        return "caution_only"
    if "trusted tester" in fact_text or "limited preview" in fact_text or "private preview" in fact_text:
        return "limited_release"
    if source_groups == {"research_papers"} or story_type == "research_result":
        return "research_watch"
    return "actionable"


def _takeaway_rule(evidence_mode: str) -> str:
    if evidence_mode == "caution_only":
        return (
            "Takeaway must be an attributed fact-based caveat. Make the source attribution clear, "
            "but do not start every sentence with the source name. "
            "Do not end with vague phrases like 'watch evolving results' or 'monitor impact'. "
            "Do not tell viewers to deploy, integrate, validate today, start using, or change workflows."
        )
    if evidence_mode == "research_watch":
        return (
            "Takeaway must name a concrete evidence gap or research caveat grounded in fact_text. "
            "Do not end with vague phrases like 'watch evolving results' or 'monitor impact'. "
            "Avoid deployment, production, integration, governance, or operator advice unless those exact ideas appear in fact_text."
        )
    if evidence_mode == "limited_release":
        return (
            "Takeaway must mention availability limits and a concrete caveat grounded in fact_text. "
            "Do not end with vague phrases like 'watch evolving results' or 'monitor impact'. "
            "Do not tell viewers to start validating, deploy, integrate, or change workflows unless fact_text explicitly supports broad availability."
        )
    return (
        "Takeaway may give practical builder/operator guidance, but only when it follows directly from fact_text."
    )


def _is_known_identity(value: str) -> bool:
    return bool(value) and value.strip().lower() not in {"unknown", "n/a", "none", "null"}


def _is_useful_action(value: str) -> bool:
    action = value.strip().lower()
    return bool(action) and action not in {"reported", "updated", "launched", "released", "announced", "disproved"}


def _pretty_identity(value: str) -> str:
    cleaned = clean_text(value).replace("_", " ")
    if not cleaned:
        return ""
    acronyms = {
        "ai": "AI",
        "api": "API",
        "aws": "AWS",
        "era": "ERA",
        "fm-cgm": "FM-CGM",
        "hipaa": "HIPAA",
        "llm": "LLM",
        "openai": "OpenAI",
    }
    words = []
    for word in cleaned.split():
        words.append(acronyms.get(word.lower(), word[:1].upper() + word[1:]))
    return " ".join(words)


def _shorten_title(title: str, limit: int) -> str:
    if len(title) <= limit:
        return title
    separators = [" — ", ": ", " with ", " for "]
    for separator in separators:
        head = title.split(separator, 1)[0]
        if 12 <= len(head) <= limit:
            return head
    words = title.split()
    shortened = ""
    for word in words:
        candidate = f"{shortened} {word}".strip()
        if len(candidate) > limit:
            break
        shortened = candidate
    return shortened or title[:limit].rstrip()


def _word_budget(target_seconds: int, words_per_minute: int) -> int:
    return max(25, int(round(target_seconds * words_per_minute / 60)))


def _minimum_words(target_seconds: int, words_per_minute: int) -> int:
    return max(20, int(round(_word_budget(target_seconds, words_per_minute) * 0.75)))
