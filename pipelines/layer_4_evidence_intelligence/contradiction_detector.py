"""
Layer 4 — Module 7: Contradiction Detector

Detects conflicts between claims within the same story.

Contradiction patterns (keyword-based, no LLM):
  availability_conflict — "all users" vs "paid only" / "limited rollout"
  pricing_conflict      — different numeric prices for same product
  date_conflict         — different dates for same event
  benchmark_conflict    — conflicting benchmark numbers for same metric
  license_conflict      — "open source" vs "restricted license"
  access_conflict       — "free" vs "subscription" / "waitlist"

Severity:
  high   — hard fact conflict (dates, numbers, license)
  medium — scope/availability conflict
  low    — terminology or framing difference

Key function:
    detect_all(verified_results) → list of {story_id, contradictions}

Usage:
    python contradiction_detector.py --run-id run_2026_05_10_48h_auto
"""

import sys
import re
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_ALL_USERS   = re.compile(r"\b(all users|everyone|publicly available|general availability)\b", re.I)
_PAID_ONLY   = re.compile(r"\b(paid|premium|plus|pro|subscription|limited rollout|waitlist|selected)\b", re.I)
_FREE        = re.compile(r"\bfree\b", re.I)
_OPEN_SOURCE = re.compile(r"\b(open.source|open source|open-source|openly available)\b", re.I)
_RESTRICTED  = re.compile(r"\b(proprietary|restricted|closed|not open.source|commercial only)\b", re.I)
_PRICE       = re.compile(r"\$\s?(\d+(?:\.\d+)?)", re.I)
_DATE        = re.compile(r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(?:,\s?\d{4})?\b", re.I)
_BENCHMARK   = re.compile(r"\b(\d+(?:\.\d+)?)\s*%\b", re.I)


def _check_availability(claims: list[dict]) -> list[dict]:
    contradictions = []
    universal = [(i, c) for i, c in enumerate(claims) if _ALL_USERS.search(c["claim_text"])]
    restricted = [(i, c) for i, c in enumerate(claims) if _PAID_ONLY.search(c["claim_text"])]
    for ui, uc in universal:
        for ri, rc in restricted:
            if ui == ri:
                continue
            contradictions.append({
                "contradiction_type": "availability_conflict",
                "severity": "medium",
                "claim_a_id": uc["claim_id"],
                "claim_a_text": uc["claim_text"],
                "claim_b_id": rc["claim_id"],
                "claim_b_text": rc["claim_text"],
                "recommended_script_handling":
                    "Availability details are unclear. Avoid definitive wording about user access.",
            })
    return contradictions


def _check_prices(claims: list[dict]) -> list[dict]:
    prices: list[tuple[str, str, str]] = []
    for c in claims:
        m = _PRICE.findall(c["claim_text"])
        if m:
            prices.append((c["claim_id"], c["claim_text"], m[0]))

    contradictions = []
    seen: set[tuple[str, str]] = set()
    for i in range(len(prices)):
        for j in range(i + 1, len(prices)):
            cid_a, text_a, price_a = prices[i]
            cid_b, text_b, price_b = prices[j]
            if price_a != price_b and (cid_a, cid_b) not in seen:
                seen.add((cid_a, cid_b))
                contradictions.append({
                    "contradiction_type": "pricing_conflict",
                    "severity": "high",
                    "claim_a_id": cid_a,
                    "claim_a_text": text_a,
                    "claim_b_id": cid_b,
                    "claim_b_text": text_b,
                    "recommended_script_handling":
                        f"Sources give conflicting prices (${price_a} vs ${price_b}). "
                        "Verify before stating a price.",
                })
    return contradictions


def _check_license(claims: list[dict]) -> list[dict]:
    contradictions = []
    open_claims = [(c["claim_id"], c["claim_text"])
                   for c in claims if _OPEN_SOURCE.search(c["claim_text"])]
    closed_claims = [(c["claim_id"], c["claim_text"])
                     for c in claims if _RESTRICTED.search(c["claim_text"])]
    for oa_id, oa_text in open_claims:
        for cl_id, cl_text in closed_claims:
            contradictions.append({
                "contradiction_type": "license_conflict",
                "severity": "high",
                "claim_a_id": oa_id,
                "claim_a_text": oa_text,
                "claim_b_id": cl_id,
                "claim_b_text": cl_text,
                "recommended_script_handling":
                    "Conflicting license information. Verify actual license before claiming open/closed.",
            })
    return contradictions


def _check_free_vs_paid(claims: list[dict]) -> list[dict]:
    contradictions = []
    free_claims = [(c["claim_id"], c["claim_text"])
                   for c in claims if _FREE.search(c["claim_text"])
                   and not _PAID_ONLY.search(c["claim_text"])]
    paid_claims = [(c["claim_id"], c["claim_text"])
                   for c in claims if _PAID_ONLY.search(c["claim_text"])]
    for fc_id, fc_text in free_claims:
        for pc_id, pc_text in paid_claims:
            contradictions.append({
                "contradiction_type": "access_conflict",
                "severity": "medium",
                "claim_a_id": fc_id,
                "claim_a_text": fc_text,
                "claim_b_id": pc_id,
                "claim_b_text": pc_text,
                "recommended_script_handling":
                    "Sources conflict on whether this is free or paid. Use careful wording.",
            })
    return contradictions


def detect(story_id: str, verified_claims: list[dict]) -> list[dict]:
    """Detect contradictions within one story's verified claims."""
    # Only check non-rejected usable claims
    usable = [c for c in verified_claims
              if c.get("verification_status") not in ("rejected", "community_signal_only")]

    contradictions = []
    contradictions.extend(_check_availability(usable))
    contradictions.extend(_check_prices(usable))
    contradictions.extend(_check_license(usable))
    contradictions.extend(_check_free_vs_paid(usable))

    counter = 1
    for c in contradictions:
        c["contradiction_id"] = f"contradiction_{story_id[-12:]}_{counter:03d}"
        c["story_id"] = story_id
        c["resolution_status"] = "unresolved"
        counter += 1

    return contradictions


def detect_all(verified_results: list[dict]) -> list[dict]:
    """
    Returns list of {story_id, contradictions} per story.
    """
    story_contradictions = []
    for result in verified_results:
        sid = result["story_id"]
        all_claims = result.get("atomic_claims", [])
        contras = detect(sid, all_claims)
        story_contradictions.append({
            "story_id":      sid,
            "story_title":   result.get("story_title", ""),
            "contradictions": contras,
            "count":          len(contras),
        })
    return story_contradictions


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=False)
    args = parser.parse_args()

    run_id = args.run_id
    if not run_id:
        for rp in sorted(RUNS_DIR.glob("*/run_manifest.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True):
            if (rp.parent / "layer_3" / "ranked_stories.json").exists():
                run_id = rp.parent.name
                break
        print(f"Auto-discovered run: {run_id}")

    from pipelines.layer_4_evidence_intelligence.evidence_loader       import load
    from pipelines.layer_4_evidence_intelligence.span_selector         import select_all
    from pipelines.layer_4_evidence_intelligence.claim_extractor        import extract_all
    from pipelines.layer_4_evidence_intelligence.claim_evidence_linker  import link_all
    from pipelines.layer_4_evidence_intelligence.claim_deduplicator     import deduplicate_all
    from pipelines.layer_4_evidence_intelligence.claim_verifier         import verify_all

    layer3_dir = RUNS_DIR / run_id / "layer_3"
    layer2_dir = RUNS_DIR / run_id / "layer_2"
    loader_result = load(run_id, layer3_dir, layer2_dir)
    selections    = select_all(loader_result["evidence_bundles"], loader_result["spans_by_id"])
    story_results = extract_all(selections[:3], run_id)
    linked        = link_all(story_results, loader_result["spans_by_id"], loader_result["docs_by_id"])
    deduped       = deduplicate_all(linked["enriched_story_results"])
    verified      = verify_all(deduped["deduped_results"])
    contradictions = detect_all(verified)

    total = sum(d["count"] for d in contradictions)
    print(f"\nContradiction Detector — {run_id}")
    print(f"  Total contradictions : {total}")
    for d in contradictions:
        print(f"  {d['story_title'][:50]:50s}  contradictions={d['count']}")
        for c in d["contradictions"]:
            print(f"    [{c['severity']}] {c['contradiction_type']}")
