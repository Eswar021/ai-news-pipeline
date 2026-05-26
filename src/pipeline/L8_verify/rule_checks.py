from __future__ import annotations

from collections import Counter

from src.pipeline.L1_collection.common import clean_text


QUALIFIERS = (
    "according to",
    "cautious",
    "cited",
    "evidence is cautious",
    "indexed in",
    "reported",
    "reports",
    "suggests",
    "appears",
    "may",
    "could",
    "potentially",
    "the paper",
    "the authors",
    "the source",
    "the study",
    "unproven",
)
VISUAL_DIRECTION_MARKERS = (
    "lower third",
    "on screen",
    "on-screen",
    "b-roll",
    "b roll",
    "overlay",
    "show on screen",
    "show this on screen",
    "show title card",
    "cut to",
    "visual note",
    "visual direction",
    "editor note",
)


def run_rule_checks(script_package: dict, sentence_map: list[dict], layer8_cfg: dict) -> dict:
    checks = []
    checks.append(_package_shape_check(script_package))
    checks.append(_section_order_check(script_package))
    checks.append(_duration_check(script_package, layer8_cfg))
    checks.append(_required_fact_usage_check(script_package))
    checks.append(_unknown_fact_usage_check(script_package))
    checks.append(_cautious_language_check(script_package))
    checks.append(_metadata_check(script_package))
    checks.append(_source_url_check(script_package))
    checks.append(_visual_direction_check(script_package))
    checks.append(_sentence_map_check(sentence_map))

    status_counts = Counter(check["status"] for check in checks)
    return {
        "passed": status_counts.get("failed", 0) == 0,
        "checks": checks,
        "status_counts": dict(status_counts),
        "errors": [check for check in checks if check["status"] == "failed"],
        "warnings": [check for check in checks if check["status"] == "warning"],
    }


def _package_shape_check(script_package: dict) -> dict:
    required = [
        "run_id",
        "package_type",
        "status",
        "video",
        "section_scripts",
        "full_script",
        "youtube_metadata",
        "source_index",
        "evidence_usage",
        "layer8_handoff",
    ]
    missing = [key for key in required if key not in script_package]
    if missing:
        return _check("package_shape", "failed", f"Missing required keys: {missing}")
    if script_package.get("package_type") != "roundup_script":
        return _check("package_shape", "failed", "L8 v1 supports only package_type='roundup_script'")
    if script_package.get("status") != "ready_for_layer_8":
        return _check("package_shape", "failed", "L7 package is not ready_for_layer_8")
    return _check("package_shape", "passed", "Required package keys are present")


def _section_order_check(script_package: dict) -> dict:
    sections = script_package.get("section_scripts", [])
    section_order = script_package.get("full_script", {}).get("section_order", [])
    actual_order = [section.get("section_id", "") for section in sections]
    if actual_order != section_order:
        return _check("section_order", "failed", "full_script.section_order does not match section_scripts order")
    if not sections or sections[0].get("section_type") != "intro" or sections[-1].get("section_type") != "closing":
        return _check("section_order", "failed", "Script must start with intro and end with closing")
    return _check("section_order", "passed", f"{len(sections)} sections in expected order")


def _duration_check(script_package: dict, layer8_cfg: dict) -> dict:
    target = int(script_package.get("video", {}).get("target_duration_seconds", 0) or 0)
    actual = float(script_package.get("full_script", {}).get("estimated_duration_seconds", 0) or 0)
    tolerance = float(layer8_cfg.get("duration_tolerance_ratio", 0.25))
    if not target or not actual:
        return _check("duration", "failed", "Missing target or estimated duration")
    low = target * (1 - tolerance)
    high = target * (1 + tolerance)
    if actual < low:
        return _check("duration", "warning", f"Script is short: {actual:.1f}s vs target {target}s")
    if actual > high:
        return _check("duration", "warning", f"Script is long: {actual:.1f}s vs target {target}s")
    return _check("duration", "passed", f"Estimated duration {actual:.1f}s is within tolerance")


def _required_fact_usage_check(script_package: dict) -> dict:
    usage = script_package.get("evidence_usage", {})
    omitted = list(usage.get("omitted_required_fact_ids", []))
    if omitted:
        return _check("required_fact_usage", "failed", f"Required facts omitted: {omitted}")
    required = set(usage.get("required_fact_ids", []))
    used_required = set(usage.get("used_required_fact_ids", []))
    missing = sorted(required - used_required)
    if missing:
        return _check("required_fact_usage", "failed", f"Required facts not used: {missing}")
    return _check("required_fact_usage", "passed", f"{len(required)} required facts used")


def _unknown_fact_usage_check(script_package: dict) -> dict:
    usage = script_package.get("evidence_usage", {})
    fact_index = usage.get("fact_index", {})
    known = set(fact_index)
    used = set(usage.get("used_fact_ids", []))
    unknown = sorted(used - known)
    if unknown:
        return _check("unknown_fact_usage", "failed", f"Used fact IDs missing from fact_index: {unknown}")
    return _check("unknown_fact_usage", "passed", f"{len(used)} used fact IDs are known")


def _cautious_language_check(script_package: dict) -> dict:
    cautious_ids = set(script_package.get("evidence_usage", {}).get("required_cautious_fact_ids", []))
    warnings = []
    for section in script_package.get("section_scripts", []):
        section_cautious = cautious_ids & set(section.get("used_fact_ids", []))
        if not section_cautious:
            continue
        text = clean_text(section.get("narration_text", "")).lower()
        if not any(qualifier in text for qualifier in QUALIFIERS):
            warnings.append(
                {
                    "section_id": section.get("section_id", ""),
                    "fact_ids": sorted(section_cautious),
                }
            )
    if warnings:
        return _check("cautious_language", "warning", "Cautious facts may need stronger qualifiers", warnings)
    return _check("cautious_language", "passed", "Cautious facts use qualifier language")


def _metadata_check(script_package: dict) -> dict:
    metadata = script_package.get("youtube_metadata", {})
    errors = []
    if len(metadata.get("title_options", [])) < 3:
        errors.append("fewer than 3 title options")
    if len(metadata.get("thumbnail_text_options", [])) < 3:
        errors.append("fewer than 3 thumbnail text options")
    if len(metadata.get("chapters", [])) != len(script_package.get("section_scripts", [])):
        errors.append("chapter count does not match section count")
    if not clean_text(metadata.get("description_draft", "")):
        errors.append("missing description draft")
    if errors:
        return _check("metadata", "failed", "; ".join(errors))
    return _check("metadata", "passed", "Metadata is complete enough for review")


def _source_url_check(script_package: dict) -> dict:
    source_urls = script_package.get("youtube_metadata", {}).get("source_urls", [])
    if not source_urls:
        return _check("source_urls", "failed", "No source URLs in metadata")
    bad_urls = [url for url in source_urls if not str(url).startswith(("http://", "https://"))]
    if bad_urls:
        return _check("source_urls", "failed", f"Invalid source URLs: {bad_urls}")
    return _check("source_urls", "passed", f"{len(source_urls)} source URLs available")


def _visual_direction_check(script_package: dict) -> dict:
    matches = []
    for section in script_package.get("section_scripts", []):
        text = clean_text(section.get("narration_text", "")).lower()
        markers = [marker for marker in VISUAL_DIRECTION_MARKERS if marker in text]
        if markers:
            matches.append({"section_id": section.get("section_id", ""), "markers": markers})
    if matches:
        return _check("visual_direction_leak", "failed", "Narration contains visual/editor directions", matches)
    return _check("visual_direction_leak", "passed", "Narration contains no visual/editor direction markers")


def _sentence_map_check(sentence_map: list[dict]) -> dict:
    if not sentence_map:
        return _check("sentence_map", "failed", "No sentences found in script")
    story_sentences = [item for item in sentence_map if item.get("section_type") == "story"]
    if not story_sentences:
        return _check("sentence_map", "failed", "No story sentences found")
    return _check("sentence_map", "passed", f"{len(sentence_map)} total sentences mapped")


def _check(name: str, status: str, detail: str, items: list | None = None) -> dict:
    return {
        "name": name,
        "status": status,
        "detail": detail,
        "items": items or [],
    }
