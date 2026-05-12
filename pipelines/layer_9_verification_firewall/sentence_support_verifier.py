"""
Layer 9 — Module 6: Sentence Support Verifier (LLM)

Uses source span text from Layer 2 to verify that script sentences do not
overstate what the raw evidence actually says.

One LLM call per content section (story/takeaway) — async via asyncio.gather().
Skips intro_hook and cta sections (no evidence verification needed).

Support statuses returned by LLM:
  directly_supported       — sentence is clearly backed by source text
  supported_with_caution   — source supports it but uses hedged language
  analysis_supported       — reasonable synthesis, not a direct factual claim
  overclaim                — sentence goes further than source text supports
  unsupported              — sentence has no basis in the provided source text

Returns:
    list of per-sentence verification records
"""

import os
import re
import json
import asyncio
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from llm.async_llm_runtime import execute_chat_request

_SKIP_SECTIONS  = {"intro_hook", "cta"}
_MAX_SPAN_CHARS = 1200  # truncate each span to keep prompt size reasonable
_MAX_SPANS      = 4     # max source spans per section

def _get_section_spans(section_key: str, classified: list, ctx: dict) -> list:
    """Collect unique source span texts for all claim_ids in this section."""
    claim_map = ctx["claim_map"]
    cem_map   = ctx["cem_map"]
    span_map  = ctx["span_map"]

    span_ids_seen = set()
    spans = []

    for sent in classified:
        if sent.get("section_key") != section_key:
            continue
        for cid in sent.get("claim_ids", []):
            cem = cem_map.get(cid, {})
            claim = claim_map.get(cid, {})
            sids = cem.get("source_span_ids", []) or claim.get("source_span_ids", [])
            for sid in sids:
                if sid not in span_ids_seen and sid in span_map:
                    span_ids_seen.add(sid)
                    spans.append(span_map[sid])
                if len(spans) >= _MAX_SPANS:
                    break
            if len(spans) >= _MAX_SPANS:
                break

    return spans


def _build_prompt(section_key: str, sentences: list, spans: list, ctx: dict) -> str:
    span_texts = []
    for i, sp in enumerate(spans[:_MAX_SPANS], 1):
        text = sp.get("text", "")[:_MAX_SPAN_CHARS]
        url  = sp.get("source_url", "")
        span_texts.append(f"[Source {i}] ({url})\n{text}")

    source_block = "\n\n".join(span_texts) if span_texts else "(No source spans available)"

    # Collect verified claim texts
    claim_map = ctx["claim_map"]
    claim_ids_seen = set()
    claim_lines = []
    for sent in sentences:
        for cid in sent.get("claim_ids", []):
            if cid not in claim_ids_seen:
                claim_ids_seen.add(cid)
                c = claim_map.get(cid, {})
                claim_lines.append(f"- [{cid}] {c.get('claim_text', '')}")

    claims_block = "\n".join(claim_lines) if claim_lines else "(none)"

    sent_block = "\n".join(
        f'- [{s["sentence_id"]}] {s["sentence_text"]}'
        for s in sentences
    )

    return f"""You are a factual verification analyst. Your job is to check whether script sentences are properly supported by their source material.

## Source Text
{source_block}

## Verified Claims (extracted from source)
{claims_block}

## Script Sentences to Verify (section: {section_key})
{sent_block}

## Instructions
For each sentence, check whether it stays within what the source text and verified claims actually say.
Do NOT be overly strict — general analytical statements that follow from the evidence are acceptable as "analysis_supported".
Flag as "overclaim" only if the sentence adds specific facts, rankings, predictions, or certainty that the source does not support.
Flag as "unsupported" only if the sentence makes claims with no connection to the source material.

Return ONLY a JSON object with this exact format:
{{
  "section_key": "{section_key}",
  "sentence_verifications": [
    {{
      "sentence_id": "sent_XXXX",
      "support_status": "directly_supported|supported_with_caution|analysis_supported|overclaim|unsupported",
      "severity": "info|warning|medium|high",
      "issue": null or "short explanation if overclaim/unsupported",
      "recommended_fix": null or "suggested replacement"
    }}
  ]
}}"""


async def _verify_section(
    run_id: str | None,
    section_key: str,
    sentences: list,
    spans: list,
    ctx: dict,
) -> list:
    if not sentences:
        return []

    prompt = _build_prompt(section_key, sentences, spans, ctx)

    try:
        data = await execute_chat_request(
            module_name="sentence_support_verifier",
            run_id=run_id,
            messages=[
                {"role": "system", "content": "You are a strict but fair factual verification analyst. Return only JSON."},
                {"role": "user",   "content": prompt},
            ],
            request_name=section_key,
            metadata={
                "section_key": section_key,
                "sentence_count": len(sentences),
                "source_span_count": len(spans),
                "sentence_ids": [s.get("sentence_id", "") for s in sentences],
            },
            parse_json=True,
        )
        verifications = data.get("sentence_verifications", [])
        # attach section_key to each
        for v in verifications:
            v["section_key"] = section_key
        return verifications
    except Exception as e:
        # If LLM fails, mark all sentences as verification_error
        return [
            {
                "sentence_id":    s["sentence_id"],
                "section_key":    section_key,
                "support_status": "verification_error",
                "severity":       "warning",
                "issue":          f"LLM error: {str(e)[:80]}",
                "recommended_fix": None,
            }
            for s in sentences
        ]


async def _verify_all(classified: list, ctx: dict) -> list:
    # Group sentences by section
    sections = {}
    for sent in classified:
        if not sent.get("requires_claim_support"):
            continue
        sk = sent.get("section_key", "")
        if sk in _SKIP_SECTIONS:
            continue
        sections.setdefault(sk, []).append(sent)

    tasks = []
    section_keys = []
    for sk, sents in sections.items():
        spans = _get_section_spans(sk, classified, ctx)
        tasks.append(_verify_section(ctx.get("run_id"), sk, sents, spans, ctx))
        section_keys.append(sk)

    results_by_section = await asyncio.gather(*tasks)

    all_verifications = []
    for verifications in results_by_section:
        all_verifications.extend(verifications)

    # Build lookup by sentence_id
    ver_by_id = {v["sentence_id"]: v for v in all_verifications}

    # Build final list for ALL sentences
    final = []
    for sent in classified:
        sid = sent["sentence_id"]
        sk  = sent.get("section_key", "")

        if not sent.get("requires_claim_support") or sk in _SKIP_SECTIONS:
            final.append({
                "sentence_id":    sid,
                "section_key":    sk,
                "sentence_text":  sent.get("sentence_text", ""),
                "support_status": "no_verification_needed",
                "severity":       "info",
                "issue":          None,
                "recommended_fix": None,
            })
        elif sid in ver_by_id:
            v = ver_by_id[sid]
            v["sentence_text"] = sent.get("sentence_text", "")
            final.append(v)
        else:
            final.append({
                "sentence_id":    sid,
                "section_key":    sk,
                "sentence_text":  sent.get("sentence_text", ""),
                "support_status": "not_verified",
                "severity":       "warning",
                "issue":          "LLM did not return result for this sentence.",
                "recommended_fix": None,
            })

    return final


def verify(classified: list, ctx: dict) -> list:
    return asyncio.run(_verify_all(classified, ctx))


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from config.paths import RUNS_DIR
    from pipelines.layer_9_verification_firewall.context_loader import load
    from pipelines.layer_9_verification_firewall.sentence_classification_validator import classify

    run_id = "run_2026_05_10_48h_auto"
    base = RUNS_DIR / run_id
    ctx = load(base / "layer_8", base / "layer_7", base / "layer_4", base / "layer_2")
    classified = classify(ctx)
    results = verify(classified, ctx)

    from collections import Counter
    status_counts = Counter(r["support_status"] for r in results)
    print(f"Total verified : {len(results)}")
    print(f"Status counts  : {dict(status_counts)}")

    issues = [r for r in results if r["support_status"] in ("overclaim", "unsupported")]
    print(f"\nIssues found   : {len(issues)}")
    for r in issues:
        print(f"  [{r['section_key']}] {r['sentence_text'][:70]}")
        print(f"    status : {r['support_status']}  severity: {r['severity']}")
        print(f"    issue  : {r.get('issue', '')}")
        print(f"    fix    : {r.get('recommended_fix', '')}")
