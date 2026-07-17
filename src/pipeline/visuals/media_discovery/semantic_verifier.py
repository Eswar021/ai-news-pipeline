from __future__ import annotations

import json
import time
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, ConfigDict, Field

from ..common import clean_text, normalize_text_list
from .llm_logging import build_llm_call_log


class MediaCandidateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    visual_match: Literal["strong", "acceptable", "weak", "mismatch"]
    identity_requirement: Literal["exact", "representative", "none"]
    identity_match: Literal[
        "confirmed",
        "compatible",
        "uncertain",
        "conflict",
        "not_applicable",
    ]
    must_show_satisfied: bool = Field(
        description="True only when every visible requirement in must_show is present."
    )
    contains_forbidden_visual: bool = Field(
        description=(
            "True only when the candidate visibly contains an element listed in must_avoid; "
            "otherwise false."
        )
    )
    recommended_action: Literal["select", "reject"] = Field(
        description="The semantic visual editor's final suitability decision for this exact scene."
    )
    confidence: float = Field(ge=0, le=1)
    reason: str


class MediaCandidateVerificationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[MediaCandidateDecision]


def verify_ranked_candidates(
    *,
    scene: dict[str, Any],
    candidates: list[dict[str, Any]],
    config: dict[str, Any],
    llm,
    system_prompt: str,
    llm_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    limit = int(config["max_candidates_per_scene"])
    selected = [candidate for candidate in candidates if _preview_url(candidate)][:limit]
    if not selected:
        return [
            {
                **candidate,
                "semantic_verification": {
                    "passed": False,
                    "reason": "No preview image was available for semantic verification.",
                },
            }
            for candidate in candidates
        ]

    expected_ids = [clean_text(candidate.get("candidate_id")) for candidate in selected]
    prompt_summary = _prompt_summary(scene, selected)
    chain = RunnableLambda(
        lambda inputs: _messages(system_prompt, scene, selected, retry_context=inputs)
    ) | llm.with_structured_output(MediaCandidateVerificationBatch, include_raw=True)
    last_error = ""
    parsed_output: dict[str, Any] | None = None
    for attempt in range(1, int(config["max_attempts"]) + 1):
        started = time.time()
        raw = None
        try:
            result = chain.invoke({"attempt": attempt, "previous_error": last_error})
            raw = result.get("raw") if isinstance(result, dict) else None
            parsed = result.get("parsed") if isinstance(result, dict) else result
            parsing_error = result.get("parsing_error") if isinstance(result, dict) else None
            if parsing_error is not None or parsed is None:
                raise ValueError(f"structured output parsing failed: {parsing_error}")
            output = (
                parsed
                if isinstance(parsed, MediaCandidateVerificationBatch)
                else MediaCandidateVerificationBatch.model_validate(parsed)
            )
            parsed_output = output.model_dump(mode="json")
            _validate_coverage(parsed_output["decisions"], expected_ids)
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            llm_calls.append(
                build_llm_call_log(
                    model=config["model"],
                    prompt_summary=prompt_summary,
                    raw_response=raw,
                    parsed_output=parsed_output,
                    metadata={
                        "scene_id": clean_text(scene.get("scene_id")),
                        "candidate_ids": expected_ids,
                        "attempt": attempt,
                    },
                    duration_seconds=time.time() - started,
                    parse_error=last_error,
                )
            )
            continue
        llm_calls.append(
            build_llm_call_log(
                model=config["model"],
                prompt_summary=prompt_summary,
                raw_response=raw,
                parsed_output=parsed_output,
                metadata={
                    "scene_id": clean_text(scene.get("scene_id")),
                    "candidate_ids": expected_ids,
                    "attempt": attempt,
                },
                duration_seconds=time.time() - started,
            )
        )
        break

    decisions = {
        clean_text(item.get("candidate_id")): item
        for item in (parsed_output or {}).get("decisions", [])
    }
    enriched: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = clean_text(candidate.get("candidate_id"))
        decision = decisions.get(candidate_id)
        if decision is None:
            verification = {
                "passed": False,
                "reason": last_error or "Candidate was outside the configured verification shortlist.",
                "status": "unverified",
            }
        else:
            verification = {
                **decision,
                "passed": decision.get("recommended_action") == "select",
                "status": "verified",
            }
        enriched.append({**candidate, "semantic_verification": verification})
    return sorted(
        enriched,
        key=lambda item: (
            not bool((item.get("semantic_verification") or {}).get("passed")),
            -float(item.get("score", 0.0) or 0.0),
            clean_text(item.get("candidate_id")),
        ),
    )
def _messages(
    system_prompt: str,
    scene: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    retry_context: dict[str, Any],
) -> list:
    task_payload = _task_payload(scene, candidates)
    if clean_text(retry_context.get("previous_error")):
        task_payload["repair_context"] = {
            "attempt": retry_context.get("attempt"),
            "previous_error": clean_text(retry_context.get("previous_error")),
            "instruction": "Return a corrected complete decision list.",
        }
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": json.dumps(task_payload, ensure_ascii=False, indent=2),
        }
    ]
    for candidate in candidates:
        content.extend(
            [
                {
                    "type": "text",
                    "text": f"Candidate image for {clean_text(candidate.get('candidate_id'))}",
                },
                {
                    "type": "image_url",
                    "image_url": {"url": _preview_url(candidate), "detail": "low"},
                },
            ]
        )
    return [SystemMessage(content=system_prompt), HumanMessage(content=content)]


def _task_payload(scene: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
    return {
        "task": "Verify which candidate visibly matches this exact narration scene.",
        "scene": {
            "scene_id": clean_text(scene.get("scene_id")),
            "render_kind": clean_text(scene.get("render_kind")),
            "story_title": clean_text(scene.get("story_title")),
            "script_excerpt": clean_text(scene.get("script_excerpt")),
            "visual_intent": clean_text(scene.get("visual_intent")),
            "search_queries": normalize_text_list(payload.get("search_queries")),
            "must_show": normalize_text_list(payload.get("must_show")),
            "must_avoid": normalize_text_list(payload.get("must_avoid")),
        },
        "candidates": [
            {
                "candidate_id": clean_text(candidate.get("candidate_id")),
                "provider": clean_text(candidate.get("provider")),
                "title": clean_text(candidate.get("title")),
                "description": clean_text(candidate.get("description")),
                "tags": candidate.get("tags", []),
                "matched_query": clean_text(candidate.get("matched_query")),
            }
            for candidate in candidates
        ],
        "required_candidate_ids": [
            clean_text(candidate.get("candidate_id")) for candidate in candidates
        ],
    }


def _prompt_summary(scene: dict[str, Any], candidates: list[dict[str, Any]]) -> str:
    return json.dumps(_task_payload(scene, candidates), ensure_ascii=False)


def _preview_url(candidate: dict[str, Any]) -> str:
    for key in ("preview_url", "download_url"):
        value = clean_text(candidate.get(key))
        if value.startswith(("http://", "https://")):
            return value
    return ""


def _validate_coverage(decisions: list[dict[str, Any]], expected_ids: list[str]) -> None:
    returned = [clean_text(item.get("candidate_id")) for item in decisions]
    if len(returned) != len(set(returned)):
        raise ValueError("media verifier returned duplicate candidate IDs")
    if set(returned) != set(expected_ids):
        raise ValueError(
            "media verifier candidate coverage mismatch; "
            f"missing={sorted(set(expected_ids) - set(returned))}, "
            f"unknown={sorted(set(returned) - set(expected_ids))}"
        )
