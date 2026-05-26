from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path

from src.llm.client import OpenAIJSONClient
from src.pipeline.L1_collection.common import clean_text


ALLOWED_VALUE_TYPES = {
    "understand_what_happened",
    "understand_why_it_matters",
    "decide_whether_to_use_tool",
    "avoid_hype",
    "learn_technical_context",
    "track_industry_shift",
    "assess_business_impact",
}
ALLOWED_AUDIENCE_FITS = {"high", "medium", "low"}
ALLOWED_ROUNDUP_SEGMENT_FITS = {"essential", "useful", "niche", "weak"}


def add_viewer_values(
    candidates: list[dict],
    *,
    layer5_cfg: dict,
    system_prompt: str,
    log_path: Path,
) -> list[dict]:
    worker_count = int(layer5_cfg["editorial_worker_count"])
    if worker_count < 1:
        raise ValueError("layer_5.editorial_worker_count must be at least 1")

    if worker_count == 1:
        return [
            _analyze_candidate(candidate, layer5_cfg=layer5_cfg, system_prompt=system_prompt, log_path=log_path)
            for candidate in candidates
        ]

    ordered: list[dict | None] = [None] * len(candidates)
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_index = {
            executor.submit(
                _analyze_candidate,
                candidate,
                layer5_cfg=layer5_cfg,
                system_prompt=system_prompt,
                log_path=log_path,
            ): index
            for index, candidate in enumerate(candidates)
        }
        for future in as_completed(future_to_index):
            candidate = future.result()
            ordered[future_to_index[future]] = candidate
            print(
                f"[L5] Viewer value done — rank={candidate['rank']} "
                f"score={candidate['viewer_value']['viewer_value_score']} "
                f"{candidate['story_title'][:70]}"
            )

    if any(candidate is None for candidate in ordered):
        raise RuntimeError("L5 viewer value analysis finished with missing candidate outputs")
    return [candidate for candidate in ordered if candidate is not None]


def _analyze_candidate(candidate: dict, *, layer5_cfg: dict, system_prompt: str, log_path: Path) -> dict:
    client = OpenAIJSONClient(model=layer5_cfg["viewer_value_model"])
    response = client.generate_json(
        module_name="viewer_value_analyzer",
        system_prompt=system_prompt,
        user_prompt=_build_user_prompt(candidate),
        log_path=log_path,
        metadata={
            "story_id": candidate["story_id"],
            "story_title": candidate["story_title"],
            "rank": candidate["rank"],
        },
    )
    viewer_value = _validate_viewer_value(response)
    return {**candidate, "viewer_value": viewer_value}


def _build_user_prompt(candidate: dict) -> str:
    packet = candidate["fact_packet"]
    safe_facts = [fact["fact_text"] for fact in packet.get("safe_facts", [])[:8]]
    cautious_facts = [fact["fact_text"] for fact in packet.get("cautious_facts", [])[:5]]
    sources = [
        {
            "source_group": record.get("source_group", ""),
            "source_name": record.get("source_name", record.get("provider", record.get("source", ""))),
            "title": record.get("title", ""),
        }
        for record in packet.get("selected_supporting_records", [])[:6]
    ]
    payload = {
        "story_title": candidate["story_title"],
        "story_type_hint": candidate["story_type_hint"],
        "readiness": candidate["readiness"],
        "editorial_value": candidate["editorial_value"],
        "story_identity": candidate.get("story_identity", {}),
        "evidence_counts": candidate["evidence_counts"],
        "sources": sources,
        "safe_facts": safe_facts,
        "cautious_facts": cautious_facts,
    }
    return (
        "Evaluate this story as one possible segment in a multi-story AI news roundup.\n"
        "Return JSON with exactly these keys: primary_viewer_question, viewer_promise, "
        "audience_fit, roundup_segment_fit, fit_reasons, value_types, "
        "viewer_value_score, why_this_story_now, blocked_angles.\n\n"
        f"Story packet:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _validate_viewer_value(response: dict) -> dict:
    required_strings = ["primary_viewer_question", "viewer_promise", "why_this_story_now"]
    for key in required_strings:
        if not clean_text(response.get(key, "")):
            raise ValueError(f"viewer_value_analyzer response missing {key}")

    raw_score = response.get("viewer_value_score")
    try:
        score = int(round(float(raw_score)))
    except (TypeError, ValueError) as exc:
        raise ValueError("viewer_value_analyzer response has invalid viewer_value_score") from exc
    if score < 0 or score > 100:
        raise ValueError("viewer_value_analyzer response viewer_value_score must be 0-100")

    value_types = response.get("value_types")
    if not isinstance(value_types, list) or not value_types:
        raise ValueError("viewer_value_analyzer response must include non-empty value_types")
    cleaned_value_types = [clean_text(value) for value in value_types]
    invalid_types = [value for value in cleaned_value_types if value not in ALLOWED_VALUE_TYPES]
    if invalid_types:
        raise ValueError(f"viewer_value_analyzer response has invalid value_types: {invalid_types}")

    audience_fit = clean_text(response.get("audience_fit", ""))
    if audience_fit not in ALLOWED_AUDIENCE_FITS:
        raise ValueError("viewer_value_analyzer response has invalid audience_fit")

    roundup_segment_fit = clean_text(response.get("roundup_segment_fit", ""))
    if roundup_segment_fit not in ALLOWED_ROUNDUP_SEGMENT_FITS:
        raise ValueError("viewer_value_analyzer response has invalid roundup_segment_fit")

    fit_reasons = response.get("fit_reasons", [])
    if not isinstance(fit_reasons, list) or not fit_reasons:
        raise ValueError("viewer_value_analyzer response must include non-empty fit_reasons")
    cleaned_fit_reasons = [clean_text(reason) for reason in fit_reasons if clean_text(reason)]
    if not cleaned_fit_reasons:
        raise ValueError("viewer_value_analyzer response must include non-empty fit_reasons")

    blocked_angles = response.get("blocked_angles", [])
    if not isinstance(blocked_angles, list):
        raise ValueError("viewer_value_analyzer response blocked_angles must be a list")

    return {
        "primary_viewer_question": clean_text(response["primary_viewer_question"]),
        "viewer_promise": clean_text(response["viewer_promise"]),
        "audience_fit": audience_fit,
        "roundup_segment_fit": roundup_segment_fit,
        "fit_reasons": cleaned_fit_reasons,
        "value_types": cleaned_value_types,
        "viewer_value_score": score,
        "why_this_story_now": clean_text(response["why_this_story_now"]),
        "blocked_angles": [clean_text(angle) for angle in blocked_angles if clean_text(angle)],
    }
