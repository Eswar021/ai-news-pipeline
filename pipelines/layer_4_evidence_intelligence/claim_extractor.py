"""
Layer 4 — Module 3: Atomic Claim Extractor

Extracts atomic factual claims from source spans using the LLM.

One structured JSON call per span. All spans within a story run concurrently
via asyncio.gather() with a semaphore (max 20 parallel calls).

Claim types (from Layer 4 taxonomy):
    event_fact, timeline_fact, product_fact, model_capability, feature_claim,
    benchmark_claim, research_claim, business_claim, partnership_claim,
    pricing_claim, quote_claim, statistic_claim, limitation_claim, risk_claim,
    community_signal_claim, interpretive_claim, prediction_claim, opinion_claim

Support levels (LLM-assigned, from the span alone):
    direct   — text explicitly states this
    indirect — text implies this, not stated outright
    partial  — text partially supports with caveats

Key function:
    extract_all(selections, run_id) → list of story extraction results
        Each result: {story_id, atomic_claims, counts}

Usage:
    python claim_extractor.py --run-id run_2026_05_10_48h_auto
"""

import sys
import json
import asyncio
import argparse
from datetime import datetime, timezone
from config.time_utils import now_project_iso
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from pipelines.runtime_manifest import get_llm_profile
from llm.async_llm_runtime import execute_chat_request

MAX_CONCURRENT = 20
MAX_CLAIMS_PER_STORY = 20

_VALID_TYPES = {
    "event_fact", "timeline_fact", "product_fact", "model_capability",
    "feature_claim", "benchmark_claim", "research_claim", "business_claim",
    "partnership_claim", "pricing_claim", "quote_claim", "statistic_claim",
    "limitation_claim", "risk_claim", "community_signal_claim",
    "interpretive_claim", "prediction_claim", "opinion_claim",
}
_VALID_SUPPORT = {"direct", "indirect", "partial"}

_SUPPORT_CONFIDENCE = {"direct": 0.90, "indirect": 0.65, "partial": 0.42}

_SYSTEM_PROMPT = """\
You are an evidence extraction specialist. Extract atomic factual claims from a source span.

Rules:
1. Extract ONLY claims explicitly present in the text. Never infer or add context.
2. Each claim must be independently verifiable from the source text alone.
3. Split compound statements into separate atomic claims (one fact per claim).
4. If the source makes a prediction or expresses an opinion, label it correctly.
5. Do not paraphrase away specifics. Keep numbers, dates, product names exact.
6. If the span contains no extractable factual claims, return an empty claims list.

Claim types (pick the best fit):
  event_fact, timeline_fact, product_fact, model_capability, feature_claim,
  benchmark_claim, research_claim, business_claim, partnership_claim,
  pricing_claim, quote_claim, statistic_claim, limitation_claim, risk_claim,
  community_signal_claim, interpretive_claim, prediction_claim, opinion_claim

Support levels (from the span text alone):
  direct   — the text explicitly states this
  indirect — the text implies this but does not state it directly
  partial  — the text partially supports this with caveats

Return only valid JSON with this exact structure:
{"claims": [{"claim_text": "...", "claim_type": "...", "support_level": "...", "verbatim_quote": "..."}]}"""


def _story_hash(story_id: str) -> str:
    parts = story_id.split("_")
    return parts[-1] if len(parts[-1]) >= 4 else story_id[-8:]


def _make_claim_id(story_id: str, counter: int) -> str:
    return f"claim_{_story_hash(story_id)}_{counter:04d}"


async def _call_llm(run_id: str, span: dict, story_title: str, story_type: str, semaphore) -> list[dict]:
    user_msg = (
        f"Story: {story_title} (type: {story_type})\n"
        f"Source type: {span.get('source_role', 'unknown')} "
        f"(trust tier: {span.get('trust_tier', '?')})\n\n"
        f"Source text:\n{span['text']}\n\n"
        "Extract atomic claims from the source text above."
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": user_msg},
    ]

    async with semaphore:
        try:
            data = await execute_chat_request(
                module_name="claim_extractor",
                run_id=run_id,
                messages=messages,
                request_name=span.get("span_id", "source_span"),
                metadata={
                    "story_title": story_title,
                    "story_type": story_type,
                    "story_id_hint": span.get("story_id", ""),
                    "span_id": span.get("span_id", ""),
                    "source_url": span.get("source_url", ""),
                },
                parse_json=True,
            )
            return data.get("claims", [])
        except Exception:
            return []


def _validate_claim(raw: dict) -> dict | None:
    text = (raw.get("claim_text") or "").strip()
    if not text:
        return None
    ctype = raw.get("claim_type", "event_fact")
    if ctype not in _VALID_TYPES:
        ctype = "event_fact"
    support = raw.get("support_level", "indirect")
    if support not in _VALID_SUPPORT:
        support = "indirect"
    return {
        "claim_text":     text,
        "claim_type":     ctype,
        "support_level":  support,
        "verbatim_quote": (raw.get("verbatim_quote") or "")[:500],
    }


async def _extract_story(run_id: str, selection: dict, semaphore) -> dict:
    sid = selection["story_id"]
    title = selection["story_title"]
    story_type = selection.get("story_type", "unknown")
    spans = selection["selected_spans"]

    tasks = [
        _call_llm(run_id, sp, title, story_type, semaphore)
        for sp in spans
    ]
    raw_results = await asyncio.gather(*tasks)

    atomic_claims: list[dict] = []
    counter = 1
    spans_with_claims = 0

    for span, raw_claims in zip(spans, raw_results):
        span_claims = 0
        for raw in raw_claims:
            validated = _validate_claim(raw)
            if not validated:
                continue
            claim = {
                "claim_id":             _make_claim_id(sid, counter),
                "story_id":             sid,
                "claim_text":           validated["claim_text"],
                "claim_type":           validated["claim_type"],
                "support_level":        validated["support_level"],
                "verbatim_quote":       validated["verbatim_quote"],
                "extracted_from_span_id": span["span_id"],
                "source_role":          span.get("source_role", ""),
                "trust_tier":           span.get("trust_tier", 4),
                "source_url":           span.get("source_url", ""),
                "extraction_confidence": _SUPPORT_CONFIDENCE[validated["support_level"]],
                "verification_status":  "pending",
                "extracted_at":         now_project_iso(),
            }
            atomic_claims.append(claim)
            counter += 1
            span_claims += 1

        if span_claims > 0:
            spans_with_claims += 1

    # Respect max claims per story — keep earliest (highest-priority span order)
    atomic_claims = atomic_claims[:MAX_CLAIMS_PER_STORY]

    return {
        "story_id":     sid,
        "story_title":  title,
        "story_type":   story_type,
        "atomic_claims": atomic_claims,
        "counts": {
            "spans_processed":  len(spans),
            "spans_with_claims": spans_with_claims,
            "claims_extracted": len(atomic_claims),
        },
    }

def extract_all(selections: list[dict], run_id: str) -> list[dict]:
    """
    Extract atomic claims from all story selections.
    Runs spans within each story concurrently; stories are sequential.
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def _run_all():
        results = []
        for sel in selections:
            result = await _extract_story(run_id, sel, semaphore)
            results.append(result)
        return results

    return asyncio.run(_run_all())


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=False)
    parser.add_argument("--story-index", type=int, default=None,
                        help="Test a single story (0-based index)")
    args = parser.parse_args()

    run_id = args.run_id
    if not run_id:
        for rp in sorted(RUNS_DIR.glob("*/run_manifest.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True):
            if (rp.parent / "layer_3" / "ranked_stories.json").exists():
                run_id = rp.parent.name
                break
        print(f"Auto-discovered run: {run_id}")

    from pipelines.layer_4_evidence_intelligence.evidence_loader import load
    from pipelines.layer_4_evidence_intelligence.span_selector import select_all

    layer3_dir = RUNS_DIR / run_id / "layer_3"
    layer2_dir = RUNS_DIR / run_id / "layer_2"
    loader_result = load(run_id, layer3_dir, layer2_dir)
    selections = select_all(loader_result["evidence_bundles"], loader_result["spans_by_id"])

    if args.story_index is not None:
        selections = [selections[args.story_index]]

    print(f"\nClaim Extractor — {run_id}")
    print(f"  Model  : {get_llm_profile('claim_extractor', run_id=run_id)['model']}")
    print(f"  Stories: {len(selections)}")
    print(f"  Spans  : {sum(s['counts']['selected'] for s in selections)}")
    print("  Extracting...\n")

    results = extract_all(selections, run_id)
    total_claims = sum(r["counts"]["claims_extracted"] for r in results)
    print(f"  Total claims extracted: {total_claims}")
    for r in results:
        c = r["counts"]
        print(f"  {r['story_title'][:50]:50s}  "
              f"spans={c['spans_processed']}  "
              f"claims={c['claims_extracted']}")
    if results:
        print(f"\n  Sample claims from '{results[0]['story_title']}':")
        for cl in results[0]["atomic_claims"][:3]:
            print(f"    [{cl['claim_type']}] {cl['claim_text'][:80]}")
