from __future__ import annotations

import json
from pathlib import Path

from src.llm.client import OpenAIJSONClient
from src.pipeline.L1_collection.common import clean_text


BLOCKED_TAG_VALUES = {
    "unknown",
    "none",
    "null",
    "n/a",
    "ai company blogs",
    "tech news apis",
    "research papers",
    "youtube podcast transcripts",
    "community signals",
    "official update",
    "industry news",
    "research result",
}

ACRONYM_TAGS = {
    "ai": "AI",
    "api": "API",
    "arxiv": "arXiv",
    "aws": "AWS",
    "cs": "CS",
    "era": "ERA",
    "fm-cgm": "FM-CGM",
    "hipaa": "HIPAA",
    "llm": "LLM",
    "openai": "OpenAI",
}


def build_youtube_metadata(
    *,
    package_draft: dict,
    content_packet: dict,
    manifest: dict,
    layer7_cfg: dict,
    prompt_bundle: dict,
    log_path: Path,
) -> dict:
    title_options = _generate_title_options(
        package_draft=package_draft,
        content_packet=content_packet,
        manifest=manifest,
        layer7_cfg=layer7_cfg,
        prompt_bundle=prompt_bundle,
        log_path=log_path,
    )
    chapters = _build_chapters(package_draft["section_scripts"])
    source_urls = _recommended_source_urls(content_packet.get("source_index", []))
    return {
        **title_options,
        "chapters": chapters,
        "description_draft": _build_description(package_draft, manifest, chapters, source_urls),
        "tags": _build_tags(package_draft, content_packet, manifest),
        "source_urls": source_urls,
    }


def _generate_title_options(
    *,
    package_draft: dict,
    content_packet: dict,
    manifest: dict,
    layer7_cfg: dict,
    prompt_bundle: dict,
    log_path: Path,
) -> dict:
    client = OpenAIJSONClient(model=layer7_cfg["title_thumbnail_model"])
    response = client.generate_json(
        module_name="title_thumbnail_planner",
        system_prompt=prompt_bundle["system"],
        user_prompt=_build_title_prompt(package_draft, content_packet, manifest),
        log_path=log_path,
        metadata={
            "package_type": package_draft["package_type"],
            "selected_format": package_draft["video"].get("selected_format", ""),
        },
    )
    return _validate_title_response(response)


def _build_title_prompt(package_draft: dict, content_packet: dict, manifest: dict) -> str:
    channel = manifest["layer_0"]["channel"]
    story_sections = [
        {
            "section_id": section["section_id"],
            "story_id": section.get("story_id", ""),
            "chapter_title": section.get("chapter_title", section.get("title", "")),
            "role": section.get("role", ""),
            "narration_preview": section.get("narration_text", "")[:700],
            "used_fact_ids": section.get("used_fact_ids", []),
        }
        for section in package_draft.get("section_scripts", [])
        if section.get("section_type") == "story"
    ]
    payload = {
        "channel_name": channel["channel_name"],
        "content_promise": channel.get("content_promise", ""),
        "video": package_draft["video"],
        "story_sections": story_sections,
        "script_preview": package_draft["full_script"]["narration_text"][:2500],
        "blocked_angles": package_draft["video"].get("blocked_angles", []),
        "required_json_schema": {
            "title_options": [
                {
                    "title": "accurate YouTube title",
                    "accuracy_risk": "low | medium | high",
                    "click_potential": "low | medium | medium_high | high",
                    "why_it_works": "short reason",
                }
            ],
            "thumbnail_text_options": ["2-4 word ALL CAPS thumbnail text"],
            "blocked_title_angles": ["misleading angle to avoid"],
        },
    }
    return (
        "Generate draft title and thumbnail options for this AI news roundup. "
        "Most title options should sell the whole episode, not one individual segment. "
        "Use the shared theme, source mix, and practical viewer promise before single-story hooks. "
        "Prefer concrete stakes over generic phrases like 'evidence-first' unless the title also names what viewers get. "
        "Thumbnail text should be specific enough to be clickable, not a generic channel slogan. "
        "Use the final script narration as the evidence for title wording; story/chapter titles are context only. "
        "Do not use stronger wording than the narration uses. "
        "Do not write final publishing copy, do not add unsupported claims, and do not use facts outside the payload.\n\n"
        f"Metadata payload:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _validate_title_response(response: dict) -> dict:
    title_options = response.get("title_options")
    if not isinstance(title_options, list) or not title_options:
        raise ValueError("title_thumbnail_planner response must include non-empty title_options")

    cleaned_titles = []
    for item in title_options[:8]:
        if isinstance(item, str):
            cleaned_titles.append(
                {
                    "title": clean_text(item),
                    "accuracy_risk": "medium",
                    "click_potential": "medium",
                    "why_it_works": "",
                }
            )
            continue
        if not isinstance(item, dict):
            raise ValueError("title_thumbnail_planner title_options entries must be objects or strings")
        title = clean_text(item.get("title", ""))
        if not title:
            continue
        cleaned_titles.append(
            {
                "title": title,
                "accuracy_risk": _allowed_value(item.get("accuracy_risk", ""), {"low", "medium", "high"}, "medium"),
                "click_potential": _allowed_value(
                    item.get("click_potential", ""),
                    {"low", "medium", "medium_high", "high"},
                    "medium",
                ),
                "why_it_works": clean_text(item.get("why_it_works", "")),
            }
        )
    if len(cleaned_titles) < 3:
        raise ValueError("title_thumbnail_planner returned too few usable title options")

    thumbnail_text_options = response.get("thumbnail_text_options", response.get("thumbnail_text", []))
    if not isinstance(thumbnail_text_options, list) or not thumbnail_text_options:
        raise ValueError("title_thumbnail_planner response must include thumbnail_text_options")
    cleaned_thumbnail = [_thumbnail_text(value) for value in thumbnail_text_options if _thumbnail_text(value)]
    if len(cleaned_thumbnail) < 3:
        raise ValueError("title_thumbnail_planner returned too few usable thumbnail options")

    blocked = response.get("blocked_title_angles", [])
    if not isinstance(blocked, list):
        raise ValueError("title_thumbnail_planner blocked_title_angles must be a list")

    return {
        "title_options": cleaned_titles,
        "thumbnail_text_options": cleaned_thumbnail[:5],
        "blocked_title_angles": [clean_text(value) for value in blocked if clean_text(value)],
    }


def _build_chapters(section_scripts: list[dict]) -> list[dict]:
    chapters = []
    elapsed_seconds = 0
    for section in section_scripts:
        chapters.append(
            {
                "timestamp": _format_timestamp(elapsed_seconds),
                "start_seconds": elapsed_seconds,
                "section_id": section["section_id"],
                "title": _chapter_title(section),
            }
        )
        elapsed_seconds += max(1, int(round(section.get("estimated_seconds", section["target_seconds"]))))
    return chapters


def _chapter_title(section: dict) -> str:
    if section["section_type"] == "intro":
        return "Intro"
    if section["section_type"] == "closing":
        return "Closing"
    return _shorten_title(clean_text(section.get("chapter_title", section["title"])), 64)


def _build_description(package_draft: dict, manifest: dict, chapters: list[dict], source_urls: list[str]) -> str:
    channel = manifest["layer_0"]["channel"]
    lines = [
        package_draft["video"].get("viewer_promise", ""),
        "",
        "Chapters:",
    ]
    lines.extend(f"{chapter['timestamp']} {chapter['title']}" for chapter in chapters)
    if source_urls:
        lines.extend(["", "Sources:"])
        lines.extend(source_urls)
    lines.extend(["", f"{channel['channel_name']} - {channel.get('content_promise', '')}"])
    return "\n".join(line for line in lines if line is not None).strip()


def _build_tags(package_draft: dict, content_packet: dict, manifest: dict) -> list[str]:
    tags = ["AI news", "artificial intelligence", "LLM", manifest["layer_0"]["channel"]["channel_name"]]
    for segment in content_packet.get("segment_plan", []):
        identity = segment.get("story_identity", {})
        for key in ("owning_org", "primary_entity", "product_or_project"):
            tag = _clean_tag(identity.get(key, ""))
            if tag:
                tags.append(tag)
    for source in content_packet.get("source_index", []):
        tag = _clean_tag(source.get("source_name", ""))
        if tag:
            tags.append(tag)
    return _dedupe([tag[:60] for tag in tags if clean_text(tag)])[:20]


def _recommended_source_urls(source_index: list[dict]) -> list[str]:
    urls = []
    for source in source_index:
        if not source.get("recommended_for_description"):
            continue
        url = clean_text(source.get("source_url", ""))
        if url:
            urls.append(url)
    return _dedupe(urls)


def _format_timestamp(seconds: int) -> str:
    minutes, remaining = divmod(max(0, seconds), 60)
    return f"{minutes}:{remaining:02d}"


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


def _allowed_value(value: str, allowed: set[str], fallback: str) -> str:
    cleaned = clean_text(value)
    return cleaned if cleaned in allowed else fallback


def _thumbnail_text(value: str) -> str:
    cleaned = clean_text(value).upper()
    if not cleaned:
        return ""
    words = cleaned.split()
    return " ".join(words[:4])


def _clean_tag(value: str) -> str:
    cleaned = clean_text(str(value)).replace("_", " ")
    if not cleaned:
        return ""
    compact = " ".join(cleaned.split())
    if compact.lower() in BLOCKED_TAG_VALUES:
        return ""
    return " ".join(_format_tag_word(word) for word in compact.split())


def _format_tag_word(word: str) -> str:
    lower = word.lower()
    if lower in ACRONYM_TAGS:
        return ACRONYM_TAGS[lower]
    if "-" in word and lower not in ACRONYM_TAGS:
        parts = [ACRONYM_TAGS.get(part.lower(), part[:1].upper() + part[1:]) for part in word.split("-")]
        return "-".join(parts)
    if word.isupper() and len(word) <= 5:
        return word
    return word[:1].upper() + word[1:]


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    kept = []
    for value in values:
        lookup = value.lower()
        if lookup in seen:
            continue
        seen.add(lookup)
        kept.append(value)
    return kept
