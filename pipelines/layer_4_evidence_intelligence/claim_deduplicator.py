"""
Layer 4 — Module 5: Claim Deduplicator

Removes near-duplicate claims within each story using Jaccard token overlap.

Two claims are duplicates if:
  1. Jaccard similarity of word tokens >= 0.65, AND
  2. Same claim_type (different types = different meaning even if similar text)

When merging:
  - Keep the claim from the lower trust tier (authoritative source wins)
  - If same tier, keep the one with higher extraction_confidence
  - Accumulate all supporting span_ids from merged claims

Produces:
  - deduplicated claims per story
  - claim_dedup_groups (records of what was merged)

Key function:
    deduplicate_all(enriched_story_results) → {deduped_results, dedup_groups}

Usage:
    python claim_deduplicator.py --run-id run_2026_05_10_48h_auto
"""

import sys
import re
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_STOPWORDS = {"the", "a", "an", "is", "are", "was", "were", "has", "have",
              "had", "be", "been", "being", "will", "would", "could", "should",
              "may", "might", "it", "its", "to", "of", "and", "or", "in",
              "on", "at", "for", "with", "that", "this", "by", "from"}

DEDUP_THRESHOLD = 0.65


def _tokens(text: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return frozenset(w for w in words if w not in _STOPWORDS)


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _better_claim(claim_a: dict, claim_b: dict) -> dict:
    """Return the more authoritative of two duplicate claims."""
    tier_a = claim_a.get("trust_tier", 4)
    tier_b = claim_b.get("trust_tier", 4)
    if tier_a != tier_b:
        return claim_a if tier_a < tier_b else claim_b
    conf_a = claim_a.get("extraction_confidence", 0.0)
    conf_b = claim_b.get("extraction_confidence", 0.0)
    return claim_a if conf_a >= conf_b else claim_b


def deduplicate(claims: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Deduplicate claims within a single story.

    Returns:
        (deduplicated_claims, dedup_group_records)
    """
    if not claims:
        return [], []

    # Pre-compute token sets
    token_sets = [_tokens(c["claim_text"]) for c in claims]
    n = len(claims)

    merged_into: dict[int, int] = {}  # idx → canonical idx

    for i in range(n):
        if i in merged_into:
            continue
        for j in range(i + 1, n):
            if j in merged_into:
                continue
            # Same type check
            if claims[i]["claim_type"] != claims[j]["claim_type"]:
                continue
            sim = _jaccard(token_sets[i], token_sets[j])
            if sim >= DEDUP_THRESHOLD:
                merged_into[j] = i  # j gets merged into i's group

    # Build canonical groups
    groups: dict[int, list[int]] = {}
    for j, i in merged_into.items():
        root = i
        while root in merged_into:
            root = merged_into[root]
        groups.setdefault(root, []).append(j)

    dedup_groups = []
    deduplicated: list[dict] = []

    for i in range(n):
        if i in merged_into:
            continue
        canonical = claims[i]
        member_indices = groups.get(i, [])
        member_span_ids = canonical.get("evidence", {}).get("source_span_ids", [])

        for j in member_indices:
            dup = claims[j]
            canonical = _better_claim(canonical, dup)
            member_span_ids = member_span_ids + dup.get("evidence", {}).get("source_span_ids", [])

        if member_indices:
            # Merge all supporting spans into canonical claim's evidence
            canonical = dict(canonical)
            evidence = dict(canonical.get("evidence", {}))
            evidence["source_span_ids"] = list(dict.fromkeys(member_span_ids))
            canonical["evidence"] = evidence

            dedup_groups.append({
                "canonical_claim_id":  canonical["claim_id"],
                "merged_claim_ids":    [claims[j]["claim_id"] for j in member_indices],
                "story_id":            canonical["story_id"],
                "canonical_claim_text": canonical["claim_text"],
            })

        deduplicated.append(canonical)

    return deduplicated, dedup_groups


def deduplicate_all(enriched_story_results: list[dict]) -> dict:
    """
    Deduplicate claims for all stories.

    Returns:
        {
          "deduped_results": [...],
          "dedup_groups":    [...],   # flat list for claim_dedup_groups.jsonl
        }
    """
    deduped_results = []
    all_dedup_groups = []

    for story_result in enriched_story_results:
        claims = story_result.get("atomic_claims", [])
        deduped_claims, groups = deduplicate(claims)
        all_dedup_groups.extend(groups)
        deduped_results.append({
            **story_result,
            "atomic_claims": deduped_claims,
            "counts": {
                **story_result.get("counts", {}),
                "after_dedup":    len(deduped_claims),
                "dedup_removed":  len(claims) - len(deduped_claims),
            },
        })

    return {
        "deduped_results": deduped_results,
        "dedup_groups":    all_dedup_groups,
    }


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

    from pipelines.layer_4_evidence_intelligence.evidence_loader      import load
    from pipelines.layer_4_evidence_intelligence.span_selector        import select_all
    from pipelines.layer_4_evidence_intelligence.claim_extractor       import extract_all
    from pipelines.layer_4_evidence_intelligence.claim_evidence_linker import link_all

    layer3_dir = RUNS_DIR / run_id / "layer_3"
    layer2_dir = RUNS_DIR / run_id / "layer_2"
    loader_result = load(run_id, layer3_dir, layer2_dir)
    selections    = select_all(loader_result["evidence_bundles"], loader_result["spans_by_id"])
    story_results = extract_all(selections[:3], run_id)  # test on 3 stories
    linker_result = link_all(story_results, loader_result["spans_by_id"], loader_result["docs_by_id"])

    dedup_result = deduplicate_all(linker_result["enriched_story_results"])

    total_before = sum(len(r["atomic_claims"]) + r["counts"].get("dedup_removed", 0)
                       for r in dedup_result["deduped_results"])
    total_after  = sum(len(r["atomic_claims"]) for r in dedup_result["deduped_results"])
    print(f"\nClaim Deduplicator — {run_id}")
    print(f"  Before dedup : {total_before}")
    print(f"  After dedup  : {total_after}")
    print(f"  Removed      : {total_before - total_after}")
    print(f"  Dedup groups : {len(dedup_result['dedup_groups'])}")
