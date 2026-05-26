from __future__ import annotations

from statistics import mean


MAX_ROUNDUP_PER_ORG = 2
MAX_ROUNDUP_PER_PRODUCT = 1
DIVERSITY_EXCEPTION_MARGIN = 8.0
MIN_PERSPECTIVE_VIEWER_SCORE = 60
MIN_PERSPECTIVE_USABLE_FACTS = 5
MIN_PERSPECTIVE_VALUABLE_FACTS = 2
MIN_PERSPECTIVE_FIT_SCORE = 10.0
MIN_RESEARCH_FIT_SCORE = 14.0
AUDIENCE_FIT_SIGNAL = {"high": 5, "medium": 1, "low": -10}
ROUNDUP_SEGMENT_FIT_SIGNAL = {"essential": 5, "useful": 2, "niche": -5, "weak": -12}
RESEARCH_ROUNDUP_VALUE_TYPES = {
    "learn_technical_context",
    "track_industry_shift",
    "assess_business_impact",
    "decide_whether_to_use_tool",
}
SCRIPT_VALUE_STORY_TYPES = {
    "business_development",
    "industry_shift",
    "model_release",
    "product_launch",
    "research_result",
    "safety_or_policy",
}


def evaluate_candidates(candidates: list[dict], layer5_cfg: dict) -> list[dict]:
    evaluated = [_evaluate_candidate(candidate, layer5_cfg) for candidate in candidates]
    return sorted(evaluated, key=lambda item: (item["opportunity_score"], -item["rank"]), reverse=True)


def choose_roundup(evaluations: list[dict], layer5_cfg: dict) -> dict:
    if not evaluations:
        return _no_video("No L4 fact packets were available for roundup selection.")

    max_roundup = int(layer5_cfg["roundup_max_stories"])
    min_roundup = int(layer5_cfg["roundup_min_stories"])
    roundup_candidates = [
        item
        for item in evaluations
        if (item["roundup_eligible"] or item["roundup_perspective_eligible"])
        and not _memory_repeat_status(item)
    ]
    selected = _select_balanced_roundup(
        roundup_candidates,
        max_roundup=max_roundup,
        min_roundup=min_roundup,
    )
    if len(selected) < min_roundup:
        selected = _fill_with_approved_drafts_if_needed(
            selected,
            evaluations,
            max_roundup=max_roundup,
            min_roundup=min_roundup,
        )

    if len(selected) < min_roundup:
        return _no_video(
            f"Only {len(selected)} candidate(s) qualified; at least {min_roundup} are required for a useful roundup."
        )

    selected = sorted(selected, key=lambda item: (item["opportunity_score"], -item["rank"]), reverse=True)
    target_seconds = int(layer5_cfg["roundup_target_seconds"])
    selected = _assign_roundup_roles(selected, target_seconds=target_seconds)
    roundup_score = mean([item["opportunity_score"] for item in selected])
    perspective_count = sum(1 for item in selected if item.get("selection_path", "").endswith("_slot"))
    return {
        "action": "create_video",
        "selected_format": "roundup",
        "confidence": _confidence(roundup_score),
        "decision_reason": (
            f"{len(selected)} stories cleared the roundup threshold with average score "
            f"{round(roundup_score, 1)}. Included {perspective_count} outside-perspective segment(s)."
        ),
        "target_duration_seconds": target_seconds,
        "selected_story_ids": [item["story_id"] for item in selected],
        "selected_evaluations": selected,
    }


def mark_selected(
    evaluations: list[dict],
    selected_story_ids: set[str],
    *,
    selected_evaluations: list[dict] | None = None,
) -> list[dict]:
    selected_by_id = {
        item["story_id"]: item
        for item in (selected_evaluations or [])
        if item["story_id"] in selected_story_ids
    }
    marked = []
    for item in evaluations:
        selected = item["story_id"] in selected_story_ids
        reasons = [] if selected else list(item.get("rejection_reasons", []))
        if not selected and not reasons:
            reasons = ["not_selected_for_roundup"]
        selectable = item.get("roundup_eligible") or item.get("roundup_perspective_eligible")
        if not selected and _memory_repeat_status(item) == "approved_not_published":
            reasons = ["already_approved_draft_memory"]
        elif not selected and _memory_repeat_status(item) == "published":
            reasons = ["already_published_memory"]
        if (
            not selected
            and selectable
            and not _memory_repeat_status(item)
            and _matches_selected_family(item, selected_by_id.values())
        ):
            reasons = ["roundup_diversity_guardrail"]

        selected_details = selected_by_id.get(item["story_id"], {})
        marked.append(
            {
                **item,
                "segment_role": selected_details.get("segment_role", item.get("segment_role", "")),
                "target_seconds": selected_details.get("target_seconds", item.get("target_seconds", 0)),
                "role_reason": selected_details.get("role_reason", item.get("role_reason", "")),
                "selection_path": selected_details.get("selection_path", item.get("selection_path", "")),
                "selected": selected,
                "rejection_reasons": reasons,
            }
        )
    return marked


def _evaluate_candidate(candidate: dict, layer5_cfg: dict) -> dict:
    evidence_score = _evidence_score(candidate)
    script_signal_score = _script_signal_score(candidate)
    risk_penalty = _risk_penalty(candidate)
    viewer_score = int(candidate["viewer_value"]["viewer_value_score"])
    opportunity_score = _clamp(round(0.6 * viewer_score + evidence_score + script_signal_score - risk_penalty, 1))

    structurally_eligible = _structurally_eligible(candidate)
    eligible = structurally_eligible and _roundup_eligible(candidate) and opportunity_score >= float(layer5_cfg["roundup_min_candidate_score"])
    perspective_type = _perspective_type(candidate)
    perspective_eligible = structurally_eligible and _perspective_eligible(candidate, perspective_type=perspective_type)
    return {
        **candidate,
        "score_components": {
            "viewer_value_score": viewer_score,
            "evidence_score": evidence_score,
            "script_signal_score": script_signal_score,
            "risk_penalty": risk_penalty,
        },
        "opportunity_score": opportunity_score,
        "roundup_eligible": eligible,
        "roundup_perspective_eligible": perspective_eligible,
        "roundup_perspective_type": perspective_type,
        "selection_path": "",
        "rejection_reasons": _rejection_reasons(candidate, eligible=eligible, perspective_eligible=perspective_eligible),
    }


def _evidence_score(candidate: dict) -> float:
    counts = candidate["evidence_counts"]
    score = min(candidate["safe_fact_count"], 8) * 3
    score += min(candidate["cautious_fact_count"], 6)
    if candidate["readiness"] == "ready":
        score += 8
    elif candidate["readiness"] == "caution":
        score += 2
    else:
        score -= 15

    first_party_official = max(0, counts["official_record_count"] - counts.get("hosted_vendor_record_count", 0))
    if first_party_official:
        score += 7
    elif counts.get("hosted_vendor_record_count", 0):
        score += 2
    if counts["research_record_count"]:
        score += 5
    if counts["news_record_count"]:
        score += 3
    if counts["youtube_record_count"]:
        score += 2
    if candidate["community_only"]:
        score -= 10
    if counts.get("hosted_vendor_record_count", 0) and not first_party_official:
        score -= 3
    return min(max(score, 0), 35)


def _script_signal_score(candidate: dict) -> float:
    score = 0
    if candidate["editorial_value"] == "high":
        score += 8
    elif candidate["editorial_value"] == "medium":
        score += 4
    elif candidate["editorial_value"] == "low":
        score -= 8
    if candidate["story_type_hint"] in SCRIPT_VALUE_STORY_TYPES:
        score += 4
    if candidate["valuable_fact_count"] >= 4:
        score += 4
    elif candidate["valuable_fact_count"] >= 2:
        score += 2
    if candidate["is_tutorial"]:
        score -= 8
    if candidate["is_event_update"] and candidate["safe_fact_count"] < 5:
        score -= 4
    if candidate["is_noise"]:
        score -= 40
    if candidate.get("memory_overlap", {}).get("memory_status") == "approved_not_published":
        score -= 4
    elif candidate.get("memory_overlap", {}).get("memory_status") == "published":
        score -= 12
    score += _viewer_fit_signal(candidate)
    return min(max(score, -30), 18)


def _risk_penalty(candidate: dict) -> float:
    penalty = 0
    if candidate["readiness"] == "insufficient":
        penalty += 20
    elif candidate["readiness"] == "caution":
        penalty += 4
    if candidate["safe_fact_count"] < 3:
        penalty += 4 if _outside_perspective_candidate(candidate) else 8
    if candidate["community_only"]:
        penalty += 18
    if (
        candidate["evidence_counts"].get("hosted_vendor_record_count", 0)
        and candidate["evidence_counts"].get("selected_record_count", 0)
        == candidate["evidence_counts"].get("hosted_vendor_record_count", 0)
    ):
        penalty += 4
    if candidate["editorial_value"] == "low":
        penalty += 10
    if candidate["is_noise"]:
        penalty += 40
    memory_status = candidate.get("memory_overlap", {}).get("memory_status", "")
    if memory_status == "approved_not_published":
        penalty += 12
    elif memory_status == "published":
        penalty += 35
    viewer_value = candidate.get("viewer_value", {})
    if viewer_value.get("audience_fit") == "low":
        penalty += 12
    if viewer_value.get("roundup_segment_fit") == "weak":
        penalty += 12
    elif viewer_value.get("roundup_segment_fit") == "niche":
        penalty += 5
    return min(penalty, 45)


def _structurally_eligible(candidate: dict) -> bool:
    if candidate["readiness"] not in {"ready", "caution"}:
        return False
    if candidate["usable_fact_count"] < 3:
        return False
    if candidate["community_only"]:
        return False
    if candidate["editorial_value"] == "low" or candidate["is_noise"]:
        return False
    if candidate.get("memory_overlap", {}).get("memory_status") == "published":
        return False
    viewer_value = candidate.get("viewer_value", {})
    if viewer_value.get("audience_fit") == "low" or viewer_value.get("roundup_segment_fit") == "weak":
        return False
    return True


def _roundup_eligible(candidate: dict) -> bool:
    if not _structurally_eligible(candidate):
        return False
    if candidate["readiness"] == "caution" and int(candidate["viewer_value"]["viewer_value_score"]) < 70:
        return False
    return True


def _select_balanced_roundup(roundup_candidates: list[dict], *, max_roundup: int, min_roundup: int) -> list[dict]:
    selected: list[dict] = []
    selected_ids: set[str] = set()
    org_counts: dict[str, int] = {}
    product_counts: dict[str, int] = {}

    for perspective_type in ("third_party_news", "research"):
        candidate = _best_perspective_candidate(roundup_candidates, perspective_type=perspective_type)
        if candidate is None:
            continue
        _try_add_candidate(
            selected,
            selected_ids,
            org_counts,
            product_counts,
            candidate,
            selection_path=f"{perspective_type}_slot",
        )
        if len(selected) >= max_roundup:
            return selected

    for candidate in roundup_candidates:
        if len(selected) >= max_roundup:
            break
        _try_add_candidate(
            selected,
            selected_ids,
            org_counts,
            product_counts,
            candidate,
            selection_path="score_fill",
        )

    if len(selected) >= min_roundup:
        return selected

    for candidate in roundup_candidates:
        if len(selected) >= min_roundup:
            break
        if candidate["story_id"] in selected_ids:
            continue
        _add_candidate(
            selected,
            selected_ids,
            org_counts,
            product_counts,
            candidate,
            selection_path="minimum_fill",
        )
    return selected[:max_roundup]


def _fill_with_approved_drafts_if_needed(
    selected: list[dict],
    evaluations: list[dict],
    *,
    max_roundup: int,
    min_roundup: int,
) -> list[dict]:
    if len(selected) >= min_roundup:
        return selected

    selected_ids = {item["story_id"] for item in selected}
    org_counts: dict[str, int] = {}
    product_counts: dict[str, int] = {}
    for item in selected:
        org_key = _org_key(item)
        product_key = _product_key(item)
        if org_key:
            org_counts[org_key] = org_counts.get(org_key, 0) + 1
        if product_key:
            product_counts[product_key] = product_counts.get(product_key, 0) + 1

    emergency_candidates = [
        item
        for item in evaluations
        if item["story_id"] not in selected_ids
        and _memory_repeat_status(item) == "approved_not_published"
        and (item.get("roundup_eligible") or item.get("roundup_perspective_eligible"))
    ]
    for candidate in emergency_candidates:
        if len(selected) >= min_roundup or len(selected) >= max_roundup:
            break
        _add_candidate(
            selected,
            selected_ids,
            org_counts,
            product_counts,
            candidate,
            selection_path="memory_minimum_fill",
        )
    return selected


def _try_add_candidate(
    selected: list[dict],
    selected_ids: set[str],
    org_counts: dict[str, int],
    product_counts: dict[str, int],
    candidate: dict,
    *,
    selection_path: str,
) -> bool:
    if candidate["story_id"] in selected_ids:
        return False

    org_key = _org_key(candidate)
    product_key = _product_key(candidate)
    over_org = bool(org_key and org_counts.get(org_key, 0) >= MAX_ROUNDUP_PER_ORG)
    over_product = bool(product_key and product_counts.get(product_key, 0) >= MAX_ROUNDUP_PER_PRODUCT)
    if (over_org or over_product) and not _beats_selected_floor(candidate, selected):
        return False

    _add_candidate(
        selected,
        selected_ids,
        org_counts,
        product_counts,
        candidate,
        selection_path=selection_path,
    )
    return True


def _add_candidate(
    selected: list[dict],
    selected_ids: set[str],
    org_counts: dict[str, int],
    product_counts: dict[str, int],
    candidate: dict,
    *,
    selection_path: str,
) -> None:
    selected.append({**candidate, "selection_path": selection_path})
    selected_ids.add(candidate["story_id"])
    org_key = _org_key(candidate)
    product_key = _product_key(candidate)
    if org_key:
        org_counts[org_key] = org_counts.get(org_key, 0) + 1
    if product_key:
        product_counts[product_key] = product_counts.get(product_key, 0) + 1


def _assign_roundup_roles(selected: list[dict], *, target_seconds: int) -> list[dict]:
    roles = _roundup_roles(len(selected))
    seconds = _roundup_seconds(roles, target_seconds)
    assigned = []
    for index, candidate in enumerate(selected):
        role = roles[index]
        assigned.append(
            {
                **candidate,
                "segment_role": role,
                "target_seconds": seconds[index],
                "role_reason": _role_reason(role),
            }
        )
    return assigned


def _roundup_roles(count: int) -> list[str]:
    if count <= 0:
        return []
    if count == 1:
        return ["lead"]
    if count == 2:
        return ["lead", "major"]
    roles = ["lead"]
    major_count = min(2, count - 1)
    roles.extend(["major"] * major_count)
    roles.extend(["brief"] * (count - len(roles)))
    return roles


def _roundup_seconds(roles: list[str], target_seconds: int) -> list[int]:
    weights = {"lead": 1.35, "major": 1.05, "brief": 0.75}
    raw_weights = [weights[role] for role in roles]
    total_weight = sum(raw_weights) or 1
    seconds = [max(35, int(round(target_seconds * weight / total_weight / 5) * 5)) for weight in raw_weights]
    drift = target_seconds - sum(seconds)
    if seconds:
        seconds[-1] += drift
    return seconds


def _role_reason(role: str) -> str:
    if role == "lead":
        return "Strongest roundup segment with the clearest viewer promise and evidence."
    if role == "major":
        return "Strong supporting segment with enough evidence for a substantial explanation."
    return "Useful AI news item, but better handled briefly to preserve pacing and diversity."


def _rejection_reasons(candidate: dict, *, eligible: bool, perspective_eligible: bool) -> list[str]:
    if eligible or perspective_eligible:
        return []
    reasons = []
    if candidate["readiness"] == "insufficient":
        reasons.append("insufficient_evidence")
    if candidate["usable_fact_count"] < 3:
        reasons.append("too_few_usable_facts")
    if candidate["community_only"]:
        reasons.append("community_only")
    if candidate["editorial_value"] == "low":
        reasons.append("low_editorial_value")
    if candidate["is_noise"]:
        reasons.append("marked_noise")
    memory_status = candidate.get("memory_overlap", {}).get("memory_status", "")
    if memory_status == "published":
        reasons.append("already_published_memory")
    elif memory_status == "approved_not_published":
        reasons.append("already_approved_draft_memory")
    if candidate.get("viewer_value", {}).get("audience_fit") == "low":
        reasons.append("low_audience_fit")
    if candidate.get("viewer_value", {}).get("roundup_segment_fit") in {"niche", "weak"}:
        reasons.append("weak_roundup_fit")
    if not reasons:
        reasons.append("below_roundup_threshold")
    return reasons


def _memory_repeat_status(candidate: dict) -> str:
    return str(candidate.get("memory_overlap", {}).get("memory_status", "")).strip().lower()


def _best_perspective_candidate(candidates: list[dict], *, perspective_type: str) -> dict | None:
    matches = [
        candidate
        for candidate in candidates
        if candidate.get("roundup_perspective_eligible")
        and candidate.get("roundup_perspective_type") == perspective_type
    ]
    if not matches:
        return None
    return sorted(
        matches,
        key=lambda item: (
            _perspective_fit_score(item),
            item["opportunity_score"],
            item["viewer_value"]["viewer_value_score"],
            item["valuable_fact_count"],
            -item["rank"],
        ),
        reverse=True,
    )[0]


def _perspective_eligible(candidate: dict, *, perspective_type: str) -> bool:
    if perspective_type not in {"third_party_news", "research"}:
        return False
    if _viewer_fit_is_weak(candidate):
        return False
    if candidate["viewer_value"]["viewer_value_score"] < MIN_PERSPECTIVE_VIEWER_SCORE:
        return False
    if candidate["usable_fact_count"] < MIN_PERSPECTIVE_USABLE_FACTS:
        return False
    if candidate["valuable_fact_count"] < MIN_PERSPECTIVE_VALUABLE_FACTS:
        return False
    min_fit_score = MIN_RESEARCH_FIT_SCORE if perspective_type == "research" else MIN_PERSPECTIVE_FIT_SCORE
    if _perspective_fit_score(candidate) < min_fit_score:
        return False
    return True


def _perspective_type(candidate: dict) -> str:
    relationships = candidate.get("source_relationship_counts", {})
    if relationships.get("third_party", 0) > 0:
        return "third_party_news"
    if relationships.get("research", 0) > 0:
        return "research"
    if relationships.get("channel_or_creator", 0) > 0:
        return "creator_or_channel"
    return "first_party_or_other"


def _outside_perspective_candidate(candidate: dict) -> bool:
    return _perspective_type(candidate) in {"third_party_news", "research", "creator_or_channel"}


def _viewer_fit_signal(candidate: dict) -> float:
    viewer_value = candidate.get("viewer_value", {})
    audience_fit = str(viewer_value.get("audience_fit", "")).strip().lower()
    segment_fit = str(viewer_value.get("roundup_segment_fit", "")).strip().lower()
    return AUDIENCE_FIT_SIGNAL.get(audience_fit, 0) + ROUNDUP_SEGMENT_FIT_SIGNAL.get(segment_fit, 0)


def _viewer_fit_is_weak(candidate: dict) -> bool:
    viewer_value = candidate.get("viewer_value", {})
    audience_fit = str(viewer_value.get("audience_fit", "")).strip().lower()
    segment_fit = str(viewer_value.get("roundup_segment_fit", "")).strip().lower()
    return audience_fit == "low" or segment_fit in {"niche", "weak"}


def _perspective_fit_score(candidate: dict) -> float:
    viewer_value = candidate.get("viewer_value", {})
    value_types = set(viewer_value.get("value_types", []))
    score = _viewer_fit_signal(candidate)
    score += min(candidate.get("valuable_fact_count", 0), 6)
    score += min(candidate.get("usable_fact_count", 0), 8) * 0.5
    score += int(viewer_value.get("viewer_value_score", 0)) / 20

    perspective_type = _perspective_type(candidate)
    if perspective_type == "research":
        score += len(value_types & RESEARCH_ROUNDUP_VALUE_TYPES) * 2
        if "track_industry_shift" in value_types:
            score += 2
        if candidate.get("story_type_hint") == "research_result":
            score += 2
        fact_type_counts = candidate.get("fact_type_counts", {})
        score += min(int(fact_type_counts.get("research_claim", 0)), 4)
        score += min(int(fact_type_counts.get("benchmark_claim", 0)), 2)
        score += min(int(fact_type_counts.get("statistic_claim", 0)), 2)
    elif perspective_type == "third_party_news":
        score += 3
        if "avoid_hype" in value_types:
            score += 2
        if "track_industry_shift" in value_types:
            score += 2
    return round(score, 2)


def _matches_selected_family(candidate: dict, selected: object) -> bool:
    candidate_org = _org_key(candidate)
    candidate_product = _product_key(candidate)
    for selected_candidate in selected:
        if candidate_product and candidate_product == _product_key(selected_candidate):
            return True
        if candidate_org and candidate_org == _org_key(selected_candidate):
            return True
    return False


def _beats_selected_floor(candidate: dict, selected: list[dict]) -> bool:
    if not selected:
        return True
    selected_floor = min(item["opportunity_score"] for item in selected)
    return candidate["opportunity_score"] >= selected_floor + DIVERSITY_EXCEPTION_MARGIN


def _org_key(candidate: dict) -> str:
    identity = candidate.get("story_identity") or {}
    return str(identity.get("owning_org") or "").strip().lower()


def _product_key(candidate: dict) -> str:
    identity = candidate.get("story_identity") or {}
    value = identity.get("product_or_project") or identity.get("canonical_story_key") or ""
    return str(value).strip().lower()


def _no_video(reason: str) -> dict:
    return {
        "action": "no_video",
        "selected_format": "roundup",
        "confidence": "low",
        "decision_reason": reason,
        "target_duration_seconds": 0,
        "selected_story_ids": [],
        "selected_evaluations": [],
    }


def _confidence(score: float) -> str:
    if score >= 82:
        return "high"
    if score >= 68:
        return "medium"
    return "low"


def _clamp(score: float) -> float:
    return min(max(score, 0.0), 100.0)
