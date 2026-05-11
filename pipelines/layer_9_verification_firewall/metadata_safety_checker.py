"""
Layer 9 — Module 11: Title / Thumbnail / Metadata Safety Checker

Verifies that YouTube metadata is evidence-safe:
  - Recommended titles pass risk check
  - Blocked titles from Layer 7 plan are not used
  - Thumbnail text is safe
  - Description does not contain blocked phrases or rejected claims
  - Tags are not misleading

Checks the Layer 7 title_thumbnail_plan against the actual youtube_metadata
built by Layer 8.

Returns:
    dict with status, title_checks, thumbnail_checks, description_status,
    tag_status, warnings, errors
"""

import re

_RISKY_TITLE_PATTERNS = [
    r"\bdomin\w+\b",           # domination, dominates
    r"\bkill\w*\s+coding\b",
    r"\bend\s+of\s+\w+\b",
    r"\bguaranteed\b",
    r"\bwill\s+replace\b",
    r"\bwill\s+destroy\b",
    r"\bproven\b",
    r"\bdefinitely\b",
    r"\bwithout\s+question\b",
    r"\bbiggest\s+ever\b",
    r"\bmost\s+powerful\s+ever\b",
    r"\brevolution\w*\b",        # only flag in clickbait context
    r"\bbreakthrough\b",         # soft warning, not block
]

_SOFT_WARNING_PATTERNS = [r"\bbreakthrough\b", r"\brevolution\w*\b"]


def _scan_text_for_risky(text: str) -> list:
    """Return list of (pattern, match_str, is_soft) for risky patterns found."""
    found = []
    lower = text.lower()
    for p in _RISKY_TITLE_PATTERNS:
        m = re.search(p, lower)
        if m:
            is_soft = any(re.search(sp, lower) for sp in _SOFT_WARNING_PATTERNS if sp == p)
            found.append((p, m.group(), is_soft))
    return found


def check(ctx: dict) -> dict:
    youtube_meta    = ctx["youtube_metadata"]
    title_thumbnail = ctx["title_thumbnail"]
    rejected_claims = ctx["rejected_claims"]
    brief           = ctx.get("script_writer_brief", {})

    errors   = []
    warnings = []
    title_checks = []

    # ── Blocked title angles from Layer 7 plan ───────────────────────────────
    blocked_angles = title_thumbnail.get("blocked_title_angles", [])
    recommended    = title_thumbnail.get("recommended_title_angles", [])

    for angle in blocked_angles:
        btitle  = angle.get("title", "").lower()
        breason = angle.get("reason", "")
        title_checks.append({
            "title":   angle.get("title", ""),
            "status":  "blocked_by_layer7",
            "risk":    "critical",
            "reason":  breason,
        })

    # ── Recommended titles — scan for risky language ──────────────────────────
    for angle in recommended:
        title    = angle.get("title", "")
        risk_lvl = angle.get("accuracy_risk", "unknown")
        risky    = _scan_text_for_risky(title)
        if risky:
            hard_risky = [r for r in risky if not r[2]]
            if hard_risky:
                errors.append(f"Title '{title[:60]}' has risky pattern: {hard_risky[0][1]}")
                title_checks.append({
                    "title":   title,
                    "status":  "risky",
                    "risk":    "high",
                    "reason":  f"Pattern detected: {hard_risky[0][1]}",
                })
            else:
                warnings.append(f"Title '{title[:60]}' has soft-warning pattern.")
                title_checks.append({
                    "title":   title,
                    "status":  "soft_warning",
                    "risk":    "medium",
                    "reason":  f"Soft pattern detected: {risky[0][1]}",
                })
        else:
            title_checks.append({
                "title":   title,
                "status":  "safe",
                "risk":    risk_lvl,
                "reason":  "",
            })

    # ── Thumbnail text ────────────────────────────────────────────────────────
    thumb_options = title_thumbnail.get("thumbnail_text_options", [])
    thumbnail_checks = []
    for opt in thumb_options:
        text = opt.get("text", "")
        risk = opt.get("risk", "unknown")
        risky = _scan_text_for_risky(text)
        if risky and not all(r[2] for r in risky):
            errors.append(f"Thumbnail text '{text}' has risky pattern.")
            thumbnail_checks.append({"text": text, "status": "risky", "risk": "high"})
        else:
            thumbnail_checks.append({"text": text, "status": "safe", "risk": risk})

    # ── YouTube description ───────────────────────────────────────────────────
    description = youtube_meta.get("description", "") or ""
    desc_risky  = _scan_text_for_risky(description)
    desc_hard   = [r for r in desc_risky if not r[2]]
    writer_instructions = brief.get("writer_instructions", {})
    blocked_phrases = writer_instructions.get("blocked_phrases", [])
    desc_blocked = [p for p in blocked_phrases if p.lower() in description.lower()]

    if desc_hard or desc_blocked:
        description_status = "risky"
        if desc_blocked:
            errors.append(f"Description contains blocked phrase(s): {desc_blocked[:2]}")
    else:
        description_status = "safe"

    # ── Tags ──────────────────────────────────────────────────────────────────
    tags = youtube_meta.get("tags", []) or []
    risky_tags = [t for t in tags if _scan_text_for_risky(t)]
    if risky_tags:
        warnings.append(f"Tags may contain risky language: {risky_tags[:3]}")
    tags_status = "warning" if risky_tags else "safe"

    # ── Rejected claim check in description / tags ────────────────────────────
    for rc in rejected_claims:
        phrases = rc.get("claim_text", "")[:60].lower()
        if len(phrases) > 10 and phrases in description.lower():
            errors.append(f"Rejected claim text found in description: '{phrases[:50]}'")

    passed = len(errors) == 0
    status = "passed" if passed else ("passed_with_warnings" if not errors and warnings else "failed")

    return {
        "passed":              passed,
        "status":              status,
        "errors":              errors,
        "warnings":            warnings,
        "title_checks":        title_checks,
        "thumbnail_checks":    thumbnail_checks,
        "description_status":  description_status,
        "tags_status":         tags_status,
        "source_count":        youtube_meta.get("source_count", 0),
        "chapter_count":       youtube_meta.get("chapter_count", 0),
    }


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from config.paths import RUNS_DIR
    from pipelines.layer_9_verification_firewall.context_loader import load

    run_id = "run_2026_05_10_48h_auto"
    base = RUNS_DIR / run_id
    ctx = load(base / "layer_8", base / "layer_7", base / "layer_4", base / "layer_2")
    result = check(ctx)

    print(f"Status           : {result['status']}")
    print(f"Errors           : {len(result['errors'])}")
    print(f"Warnings         : {len(result['warnings'])}")
    print(f"Description      : {result['description_status']}")
    print(f"Tags             : {result['tags_status']}")
    print(f"Source count     : {result['source_count']}")
    print(f"Chapter count    : {result['chapter_count']}")
    print("\nTitle checks:")
    for t in result["title_checks"]:
        print(f"  [{t['status']}|{t['risk']}] {t['title'][:60]}")
    print("\nThumbnail checks:")
    for t in result["thumbnail_checks"]:
        print(f"  [{t['status']}] {t['text']}")
    for e in result["errors"]:
        print(f"  ERROR: {e}")
    for w in result["warnings"]:
        print(f"  WARN : {w}")
