"""
Layer 9 — Editorial Analysis Validator

Checks the small set of narration sentences that are allowed to be editorial
analysis rather than directly claim-mapped factual statements.
"""

from __future__ import annotations

import re


_ALLOWED_SECTIONS = {"final_takeaway", "outro"}
_CERTAINTY_MARKERS = {
    "definitely", "certainly", "guaranteed", "guarantees", "inevitable",
    "undoubtedly", "proves", "will", "always", "never",
}
_PRESCRIPTIVE_MARKERS = {
    "you should", "teams should", "companies should", "the move will",
    "this will", "must", "need to", "have to",
}
_NAMED_ENTITY_ALLOWLIST = {
    "AI", "LLM", "GPU", "API", "OpenAI", "Anthropic", "Google", "Meta",
    "Microsoft", "Claude", "ChatGPT", "GPT",
    "The", "This", "That", "These", "Those", "Across", "So", "And", "But",
}


def _normalized_tokens(text: str) -> set[str]:
    return set(re.findall(r"[A-Za-z0-9_.-]+", text))


def _section_claim_tokens(section_key: str, ctx: dict) -> set[str]:
    sections = ctx.get("section_scripts", {}).get("sections", [])
    claim_map = ctx.get("claim_map", {})
    claim_ids = []
    for section in sections:
        if section.get("section_key") == section_key:
            claim_ids = section.get("used_claim_ids", [])
            break

    tokens: set[str] = set()
    for claim_id in claim_ids:
        claim = claim_map.get(claim_id, {})
        tokens.update(_normalized_tokens(claim.get("claim_text", "")))
    return tokens


def validate(classified_sentences: list[dict], ctx: dict) -> dict:
    issues = []
    checked = 0

    for sent in classified_sentences:
        if sent.get("verified_sentence_type") != "editorial_analysis":
            continue

        checked += 1
        section_key = sent.get("section_key", "")
        text = sent.get("sentence_text", "")
        lower = text.lower()

        if section_key not in _ALLOWED_SECTIONS:
            issues.append({
                "sentence_id": sent.get("sentence_id", ""),
                "section_key": section_key,
                "severity": "high",
                "message": "Editorial-analysis narration is only allowed in closing-analysis sections.",
                "issue_type": "disallowed_section",
                "sentence_text": text,
            })

        if re.search(r"\d", text):
            issues.append({
                "sentence_id": sent.get("sentence_id", ""),
                "section_key": section_key,
                "severity": "high",
                "message": "Editorial-analysis narration introduced a number or metric.",
                "issue_type": "new_number",
                "sentence_text": text,
            })

        if any(marker in lower for marker in _CERTAINTY_MARKERS):
            issues.append({
                "sentence_id": sent.get("sentence_id", ""),
                "section_key": section_key,
                "severity": "high",
                "message": "Editorial-analysis narration uses certainty language.",
                "issue_type": "certainty_language",
                "sentence_text": text,
            })

        if any(marker in lower for marker in _PRESCRIPTIVE_MARKERS):
            issues.append({
                "sentence_id": sent.get("sentence_id", ""),
                "section_key": section_key,
                "severity": "medium",
                "message": "Editorial-analysis narration uses future or prescriptive framing.",
                "issue_type": "prescriptive_language",
                "sentence_text": text,
            })

        allowed_tokens = _section_claim_tokens(section_key, ctx)
        capitalized_tokens = {
            token for token in re.findall(r"\b[A-Z][A-Za-z0-9_.-]+\b", text)
            if token not in _NAMED_ENTITY_ALLOWLIST
        }
        unexpected = sorted(token for token in capitalized_tokens if token not in allowed_tokens)
        if unexpected:
            issues.append({
                "sentence_id": sent.get("sentence_id", ""),
                "section_key": section_key,
                "severity": "high",
                "message": f"Editorial-analysis narration introduced new named entities: {unexpected[:4]}",
                "issue_type": "new_named_entity",
                "sentence_text": text,
            })

    return {
        "passed": len(issues) == 0,
        "checked": checked,
        "issue_count": len(issues),
        "issues": issues,
    }
