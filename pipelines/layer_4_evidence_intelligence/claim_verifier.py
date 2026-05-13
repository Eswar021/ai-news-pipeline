"""
Layer 4 — Module 6: Claim Verifier

Rule-based claim verification. Combines:
  - Trust tier verification (4.9 Claim Support Verifier)
  - Corroboration classification (4.10 Cross-Source Corroboration)
  - Uncertainty & confidence classification (4.12)

No LLM. Uses support_level + trust_tier + claim_type rules.

Verification decision table:
  claim_type in (prediction_claim, opinion_claim)
      → rejected,    confidence=unknown,  usable=False
  claim_type == community_signal_claim + trust_tier >= 3
      → community_signal_only, not a factual verification
  claim_type == benchmark_claim + trust_tier > 1
      → uncertain,   confidence=low,      usable=True (with qualifier)
  support_level=direct  + trust_tier 1   → verified,             confidence=high
  support_level=direct  + trust_tier 2   → verified,             confidence=medium
  support_level=direct  + trust_tier 3+  → partially_supported,  confidence=low
  support_level=indirect + any tier      → partially_supported,  confidence=medium
  support_level=partial  + any tier      → uncertain,            confidence=low

Confidence scores:
  high   → 0.92
  medium → 0.72
  low    → 0.45
  unknown→ 0.0

Key function:
    verify_all(deduped_results) → list of story results with verified/rejected claims

Usage:
    python claim_verifier.py --run-id run_2026_05_10_48h_auto
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_REJECT_TYPES   = {"prediction_claim", "opinion_claim"}
_SCORE_MAP      = {"high": 0.92, "medium": 0.72, "low": 0.45, "unknown": 0.0}
_QUALIFIER_MAP  = {
    "medium": "According to available sources,",
    "low":    "The available sources suggest, though this is not fully confirmed,",
}


def _verify_one(claim: dict) -> dict:
    ctype   = claim.get("claim_type", "event_fact")
    support = claim.get("support_level", "indirect")
    tier    = claim.get("trust_tier", 4)

    if claim.get("unresolved_provenance"):
        return _make_result(
            claim,
            "rejected",
            "unknown",
            rejection_reason="unresolved_provenance",
        )

    # Rejections
    if ctype in _REJECT_TYPES:
        return _make_result(claim, "rejected", "unknown",
                            rejection_reason=f"claim_type_{ctype}")

    if ctype == "community_signal_claim":
        return _make_result(claim, "community_signal_only", "low",
                            requires_cautious_language=True,
                            qualifier="Community discussion indicates that")

    # Benchmark claims from non-official sources need extra care
    if ctype == "benchmark_claim" and tier > 1:
        return _make_result(claim, "uncertain", "low",
                            requires_cautious_language=True,
                            qualifier=_QUALIFIER_MAP["low"])

    # Core verification logic
    if support == "direct":
        if tier <= 1.5:
            return _make_result(claim, "verified", "high")
        if tier <= 2.5:
            return _make_result(claim, "verified", "medium",
                                requires_cautious_language=True,
                                qualifier=_QUALIFIER_MAP["medium"])
        return _make_result(claim, "partially_supported", "low",
                            requires_cautious_language=True,
                            qualifier=_QUALIFIER_MAP["low"])

    if support == "indirect":
        return _make_result(claim, "partially_supported", "medium",
                            requires_cautious_language=True,
                            qualifier=_QUALIFIER_MAP["medium"])

    # partial support
    return _make_result(claim, "uncertain", "low",
                        requires_cautious_language=True,
                        qualifier=_QUALIFIER_MAP["low"])


def _make_result(claim: dict, status: str, confidence: str,
                 rejection_reason: str = None,
                 requires_cautious_language: bool = False,
                 qualifier: str = "") -> dict:
    score = _SCORE_MAP[confidence]
    usable = status in ("verified", "partially_supported", "uncertain") and \
             status != "community_signal_only"
    if status == "rejected":
        usable = False

    verified = {
        **claim,
        "verification_status":      status,
        "confidence_label":         confidence,
        "confidence_score":         score,
        "requires_cautious_language": requires_cautious_language,
        "recommended_qualifier":    qualifier,
        "usable_in_script":         usable and not rejection_reason,
    }
    if rejection_reason:
        verified["rejection_reason"] = rejection_reason
    return verified


def verify_all(deduped_results: list[dict]) -> list[dict]:
    """
    Verify all claims for all stories.

    Enriches each story result with:
      - atomic_claims: all claims (now with verification fields)
      - verified_claims: list of verified + partially_supported + uncertain
      - rejected_claims: predictions, opinions, no-support
    """
    verified_results = []

    for story_result in deduped_results:
        verified: list[dict] = []
        rejected: list[dict] = []

        for claim in story_result.get("atomic_claims", []):
            result = _verify_one(claim)
            if result["verification_status"] in ("rejected", "community_signal_only"):
                rejected.append(result)
            else:
                verified.append(result)

        verified_results.append({
            **story_result,
            "atomic_claims":   verified + rejected,
            "verified_claims": verified,
            "rejected_claims": rejected,
            "counts": {
                **story_result.get("counts", {}),
                "verified":  len(verified),
                "rejected":  len(rejected),
                "high_confidence":   sum(1 for c in verified if c["confidence_label"] == "high"),
                "medium_confidence": sum(1 for c in verified if c["confidence_label"] == "medium"),
                "low_confidence":    sum(1 for c in verified if c["confidence_label"] == "low"),
            },
        })

    return verified_results


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

    layer3_dir = RUNS_DIR / run_id / "layer_3"
    layer2_dir = RUNS_DIR / run_id / "layer_2"
    loader_result = load(run_id, layer3_dir, layer2_dir)
    selections    = select_all(loader_result["evidence_bundles"], loader_result["spans_by_id"])
    story_results = extract_all(selections[:3], run_id)
    linked        = link_all(story_results, loader_result["spans_by_id"], loader_result["docs_by_id"])
    deduped       = deduplicate_all(linked["enriched_story_results"])
    verified      = verify_all(deduped["deduped_results"])

    print(f"\nClaim Verifier — {run_id}")
    for r in verified:
        c = r["counts"]
        print(f"  {r['story_title'][:50]:50s}  "
              f"ver={c.get('verified',0)}  "
              f"rej={c.get('rejected',0)}  "
              f"high={c.get('high_confidence',0)}  "
              f"med={c.get('medium_confidence',0)}")
