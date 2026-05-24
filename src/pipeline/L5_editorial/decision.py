from __future__ import annotations

from statistics import mean


MAX_ROUNDUP_PER_ORG = 2
MAX_ROUNDUP_PER_PRODUCT = 1
DIVERSITY_EXCEPTION_MARGIN = 8.0
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


def choose_video(evaluations: list[dict], layer5_cfg: dict) -> dict:
    if not evaluations:
        return _no_video("No L4 fact packets were available for editorial selection.", [])

    max_roundup = int(layer5_cfg["roundup_max_stories"])
    min_roundup = int(layer5_cfg["roundup_min_stories"])
    deep_min = float(layer5_cfg["deep_dive_min_opportunity_score"])
    no_video_min = float(layer5_cfg["no_video_min_candidate_score"])
    margin = float(layer5_cfg["deep_dive_roundup_margin"])

    deep_candidates = [item for item in evaluations if item["deep_dive_eligible"]]
    roundup_candidates = [item for item in evaluations if item["roundup_eligible"]]

    best_deep = deep_candidates[0] if deep_candidates else None
    selected_roundup = _select_balanced_roundup(roundup_candidates, max_roundup=max_roundup, min_roundup=min_roundup)
    roundup_score = mean([item["opportunity_score"] for item in selected_roundup]) if len(selected_roundup) >= min_roundup else 0.0

    if best_deep and best_deep["opportunity_score"] >= deep_min and best_deep["opportunity_score"] >= roundup_score + margin:
        return _create_video(
            selected_format="deep_dive",
            selected=_assign_segment_roles([best_deep], selected_format="deep_dive", target_seconds=int(layer5_cfg["deep_dive_target_seconds"])),
            confidence=_confidence(best_deep["opportunity_score"]),
            reason=(
                f"Top story cleared deep-dive threshold with score {best_deep['opportunity_score']} "
                f"and beat roundup score {round(roundup_score, 1)} by at least {margin}."
            ),
            target_seconds=int(layer5_cfg["deep_dive_target_seconds"]),
        )

    if len(selected_roundup) >= min_roundup:
        return _create_video(
            selected_format="roundup",
            selected=_assign_segment_roles(selected_roundup, selected_format="roundup", target_seconds=int(layer5_cfg["roundup_target_seconds"])),
            confidence=_confidence(roundup_score),
            reason=f"{len(selected_roundup)} stories cleared the roundup threshold with average score {round(roundup_score, 1)}.",
            target_seconds=int(layer5_cfg["roundup_target_seconds"]),
        )

    fallback = _best_fallback_deep_dive(evaluations)
    if fallback and fallback["opportunity_score"] >= no_video_min:
        return _create_video(
            selected_format="deep_dive",
            selected=_assign_segment_roles([fallback], selected_format="deep_dive", target_seconds=int(layer5_cfg["deep_dive_target_seconds"])),
            confidence=_confidence(fallback["opportunity_score"]),
            reason=f"Roundup was too weak, but the best story cleared fallback video threshold with score {fallback['opportunity_score']}.",
            target_seconds=int(layer5_cfg["deep_dive_target_seconds"]),
        )

    return _no_video("No candidate cleared the minimum video threshold with sufficient evidence.", evaluations)


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
            reasons = ["not_selected_by_format_decision"]
        if not selected and item.get("roundup_eligible") and _matches_selected_family(item, selected_by_id.values()):
            reasons = ["roundup_diversity_guardrail"]
        selected_details = selected_by_id.get(item["story_id"], {})
        marked.append(
            {
                **item,
                "segment_role": selected_details.get("segment_role", item.get("segment_role", "")),
                "target_seconds": selected_details.get("target_seconds", item.get("target_seconds", 0)),
                "role_reason": selected_details.get("role_reason", item.get("role_reason", "")),
                "selected": selected,
                "rejection_reasons": reasons,
            }
        )
    return marked


def _matches_selected_family(candidate: dict, selected: object) -> bool:
    candidate_org = _org_key(candidate)
    candidate_product = _product_key(candidate)
    for selected_candidate in selected:
        if candidate_product and candidate_product == _product_key(selected_candidate):
            return True
        if candidate_org and candidate_org == _org_key(selected_candidate):
            return True
    return False


def _evaluate_candidate(candidate: dict, layer5_cfg: dict) -> dict:
    evidence_score = _evidence_score(candidate)
    script_signal_score = _script_signal_score(candidate)
    risk_penalty = _risk_penalty(candidate)
    viewer_score = int(candidate["viewer_value"]["viewer_value_score"])
    opportunity_score = _clamp(round(0.6 * viewer_score + evidence_score + script_signal_score - risk_penalty, 1))

    deep_eligible = _deep_dive_eligible(candidate)
    roundup_eligible = _roundup_eligible(candidate) and opportunity_score >= float(layer5_cfg["roundup_min_candidate_score"])
    rejection_reasons = _rejection_reasons(candidate, deep_eligible=deep_eligible, roundup_eligible=roundup_eligible)

    return {
        **candidate,
        "score_components": {
            "viewer_value_score": viewer_score,
            "evidence_score": evidence_score,
            "script_signal_score": script_signal_score,
            "risk_penalty": risk_penalty,
        },
        "opportunity_score": opportunity_score,
        "deep_dive_eligible": deep_eligible,
        "roundup_eligible": roundup_eligible,
        "rejection_reasons": rejection_reasons,
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
    return min(max(score, -30), 18)


def _risk_penalty(candidate: dict) -> float:
    penalty = 0
    if candidate["readiness"] == "insufficient":
        penalty += 20
    elif candidate["readiness"] == "caution":
        penalty += 6
    if candidate["safe_fact_count"] < 3:
        penalty += 8
    if candidate["community_only"]:
        penalty += 18
    if candidate["evidence_counts"].get("hosted_vendor_record_count", 0) and candidate["evidence_counts"].get("selected_record_count", 0) == candidate["evidence_counts"].get("hosted_vendor_record_count", 0):
        penalty += 4
    if candidate["editorial_value"] == "low":
        penalty += 10
    if candidate["is_noise"]:
        penalty += 40
    return min(penalty, 45)


def _deep_dive_eligible(candidate: dict) -> bool:
    if candidate["readiness"] != "ready":
        return False
    if candidate["safe_fact_count"] < 5:
        return False
    if candidate["community_only"]:
        return False
    if candidate["editorial_value"] == "low" or candidate["is_noise"]:
        return False
    return True


def _select_balanced_roundup(roundup_candidates: list[dict], *, max_roundup: int, min_roundup: int) -> list[dict]:
    selected: list[dict] = []
    skipped: list[dict] = []
    org_counts: dict[str, int] = {}
    product_counts: dict[str, int] = {}

    for candidate in roundup_candidates:
        if len(selected) >= max_roundup:
            break

        org_key = _org_key(candidate)
        product_key = _product_key(candidate)
        over_org = bool(org_key and org_counts.get(org_key, 0) >= MAX_ROUNDUP_PER_ORG)
        over_product = bool(product_key and product_counts.get(product_key, 0) >= MAX_ROUNDUP_PER_PRODUCT)
        if (over_org or over_product) and not _beats_selected_floor(candidate, selected):
            skipped.append({**candidate, "rejection_reasons": ["roundup_diversity_guardrail"]})
            continue

        selected.append(candidate)
        if org_key:
            org_counts[org_key] = org_counts.get(org_key, 0) + 1
        if product_key:
            product_counts[product_key] = product_counts.get(product_key, 0) + 1

    if len(selected) >= min_roundup:
        return selected

    selected_ids = {item["story_id"] for item in selected}
    for candidate in roundup_candidates:
        if len(selected) >= min_roundup:
            break
        if candidate["story_id"] in selected_ids:
            continue
        selected.append(candidate)
        selected_ids.add(candidate["story_id"])
    return selected[:max_roundup]


def _beats_selected_floor(candidate: dict, selected: list[dict]) -> bool:
    if not selected:
        return True
    selected_floor = min(item["opportunity_score"] for item in selected)
    return candidate["opportunity_score"] >= selected_floor + DIVERSITY_EXCEPTION_MARGIN


def _assign_segment_roles(selected: list[dict], *, selected_format: str, target_seconds: int) -> list[dict]:
    if selected_format == "deep_dive":
        return [
            {
                **selected[0],
                "segment_role": "deep_dive",
                "target_seconds": target_seconds,
                "role_reason": "Single strongest story selected for a focused deep dive.",
            }
        ]

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
                "role_reason": _role_reason(role, index),
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


def _role_reason(role: str, index: int) -> str:
    if role == "lead":
        return "Highest editorial opportunity among the selected roundup stories."
    if role == "major":
        return "Strong supporting segment with enough evidence for a substantial explanation."
    return "Useful story, but better handled as a shorter segment to preserve pacing and diversity."


def _org_key(candidate: dict) -> str:
    identity = candidate.get("story_identity") or {}
    return str(identity.get("owning_org") or "").strip().lower()


def _product_key(candidate: dict) -> str:
    identity = candidate.get("story_identity") or {}
    value = identity.get("product_or_project") or identity.get("canonical_story_key") or ""
    return str(value).strip().lower()


def _roundup_eligible(candidate: dict) -> bool:
    if candidate["readiness"] not in {"ready", "caution"}:
        return False
    if candidate["usable_fact_count"] < 3:
        return False
    if candidate["editorial_value"] == "low" or candidate["is_noise"]:
        return False
    return True


def _best_fallback_deep_dive(evaluations: list[dict]) -> dict | None:
    for candidate in evaluations:
        if candidate["readiness"] == "insufficient":
            continue
        if candidate["community_only"]:
            continue
        if candidate["usable_fact_count"] < 3:
            continue
        if candidate["editorial_value"] == "low" or candidate["is_noise"]:
            continue
        return candidate
    return None


def _rejection_reasons(candidate: dict, *, deep_eligible: bool, roundup_eligible: bool) -> list[str]:
    if deep_eligible or roundup_eligible:
        return []
    reasons = []
    if candidate["readiness"] == "insufficient":
        reasons.append("insufficient_evidence")
    if candidate["safe_fact_count"] < 3:
        reasons.append("too_few_safe_facts")
    if candidate["community_only"]:
        reasons.append("community_only")
    if candidate["editorial_value"] == "low":
        reasons.append("low_editorial_value")
    if candidate["is_noise"]:
        reasons.append("marked_noise")
    if not reasons:
        reasons.append("below_editorial_threshold")
    return reasons


def _create_video(*, selected_format: str, selected: list[dict], confidence: str, reason: str, target_seconds: int) -> dict:
    return {
        "action": "create_video",
        "selected_format": selected_format,
        "confidence": confidence,
        "decision_reason": reason,
        "target_duration_seconds": target_seconds,
        "selected_story_ids": [item["story_id"] for item in selected],
        "selected_evaluations": selected,
    }


def _no_video(reason: str, evaluations: list[dict]) -> dict:
    return {
        "action": "no_video",
        "selected_format": "none",
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
