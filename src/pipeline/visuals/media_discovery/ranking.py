from __future__ import annotations

from typing import Any

from ..common import clean_text, meaningful_words, safe_float, safe_int


PROVIDER_QUALITY = {
    "wikimedia": 0.86,
    "pexels": 0.92,
    "pixabay": 0.88,
}


def rank_candidates(
    candidates: list[dict[str, Any]],
    *,
    query: str,
    visual_intent: str,
    must_show: list[str],
    must_avoid: list[str],
    scene_duration_seconds: float,
    preferred_aspect_ratio: float,
    min_image_width: int,
    min_image_height: int,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    desired_words = set(meaningful_words(" ".join([query, visual_intent, *must_show])))
    avoid_words = set(meaningful_words(" ".join(must_avoid)))
    for candidate in candidates:
        blob = " ".join(
            [
                clean_text(candidate.get("title", "")),
                clean_text(candidate.get("description", "")),
                " ".join(str(tag) for tag in candidate.get("tags", []) if tag),
            ]
        )
        candidate_words = set(meaningful_words(blob))
        lexical = len(desired_words & candidate_words) / max(1, len(desired_words))
        avoid_penalty = min(0.45, len(avoid_words & candidate_words) * 0.12)
        width = safe_int(candidate.get("width"), 0)
        height = safe_int(candidate.get("height"), 0)
        aspect = width / height if width > 0 and height > 0 else 0.0
        aspect_score = max(0.0, 1.0 - abs(aspect - preferred_aspect_ratio) / preferred_aspect_ratio) if aspect else 0.35
        resolution_score = min(1.0, min(width / max(1, min_image_width), height / max(1, min_image_height))) if width and height else 0.35
        duration = safe_float(candidate.get("duration_seconds"), 0.0)
        if candidate.get("media_type") == "video":
            if duration < scene_duration_seconds:
                duration_score = max(0.0, duration / max(1.0, scene_duration_seconds))
            elif duration <= 90:
                duration_score = 1.0
            else:
                duration_score = max(0.35, 90.0 / duration)
        else:
            duration_score = 1.0
        provider_score = PROVIDER_QUALITY.get(clean_text(candidate.get("provider", "")), 0.75)
        provider_rank = max(1, safe_int(candidate.get("provider_rank"), 1))
        search_rank_score = 1.0 / (1.0 + (provider_rank - 1) * 0.18)
        license_score = 1.0 if clean_text(candidate.get("license", "")) else 0.35
        score = (
            lexical * 0.36
            + aspect_score * 0.16
            + resolution_score * 0.12
            + duration_score * 0.10
            + provider_score * 0.08
            + search_rank_score * 0.10
            + license_score * 0.08
            - avoid_penalty
        )
        ranked.append(
            {
                **candidate,
                "score": round(max(0.0, score), 4),
                "score_breakdown": {
                    "semantic_keyword_match": round(lexical, 4),
                    "aspect_ratio": round(aspect_score, 4),
                    "resolution": round(resolution_score, 4),
                    "duration_fit": round(duration_score, 4),
                    "provider_quality": round(provider_score, 4),
                    "provider_search_rank": round(search_rank_score, 4),
                    "license_metadata": round(license_score, 4),
                    "avoid_penalty": round(avoid_penalty, 4),
                },
            }
        )
    return sorted(ranked, key=lambda item: (-safe_float(item.get("score"), 0.0), clean_text(item.get("candidate_id", ""))))
