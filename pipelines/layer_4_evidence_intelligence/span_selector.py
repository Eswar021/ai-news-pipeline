"""
Layer 4 — Module 2: Span Selector

Decides which source spans are sent to the LLM for claim extraction.

Selection rules (in order):
  1. Trend-signal spans (community/social) → excluded from factual extraction,
     preserved as audience_signal_spans only.
  2. Spans with is_claim_candidate=False → excluded (marked skip_not_claim_candidate).
  3. Spans with content_completeness in (title_only, metadata_only) → excluded.
  4. All remaining primary / secondary / research / technical spans → selected.

Key function:
    select(evidence_bundle, spans_by_id)
        → {story_id, selected_spans, excluded_spans, audience_signal_spans}

Usage:
    python span_selector.py --run-id run_2026_05_10_48h_auto
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_SKIP_COMPLETENESS = {"title_only", "metadata_only"}


def select(evidence_bundle: dict, spans_by_id: dict) -> dict:
    """
    Select spans from a single evidence bundle for LLM claim extraction.

    Returns:
        {
          "story_id": str,
          "selected_spans": [span, ...],      # → goes to claim_extractor
          "excluded_spans": [{span_id, reason}, ...],
          "audience_signal_spans": [span, ...],  # trend signals
        }
    """
    sid = evidence_bundle["story_id"]
    bundle = evidence_bundle["evidence_spans"]

    selected: list[dict] = []
    excluded: list[dict] = []
    audience_signals: list[dict] = []

    def _try_span(span_id: str, bucket: str):
        sp = spans_by_id.get(span_id)
        if not sp:
            excluded.append({"span_id": span_id, "reason": "span_not_found"})
            return

        if bucket == "trend_signal_spans":
            audience_signals.append(sp)
            return

        if not sp.get("is_claim_candidate", True):
            excluded.append({"span_id": span_id, "reason": "skip_not_claim_candidate"})
            return

        doc_completeness = sp.get("content_completeness", "full")
        if doc_completeness in _SKIP_COMPLETENESS:
            excluded.append({"span_id": span_id,
                             "reason": f"skip_completeness_{doc_completeness}"})
            return

        selected.append(sp)

    for bucket_name, span_ids in bundle.items():
        for sid_span in span_ids:
            _try_span(sid_span, bucket_name)

    return {
        "story_id":              evidence_bundle["story_id"],
        "story_title":           evidence_bundle["story_title"],
        "story_type":            evidence_bundle.get("story_type", ""),
        "selected_spans":        selected,
        "excluded_spans":        excluded,
        "audience_signal_spans": audience_signals,
        "counts": {
            "selected":        len(selected),
            "excluded":        len(excluded),
            "audience_signal": len(audience_signals),
        },
    }


def select_all(evidence_bundles: list[dict], spans_by_id: dict) -> list[dict]:
    return [select(bundle, spans_by_id) for bundle in evidence_bundles]


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

    from pipelines.layer_4_evidence_intelligence.evidence_loader import load
    layer3_dir = RUNS_DIR / run_id / "layer_3"
    layer2_dir = RUNS_DIR / run_id / "layer_2"
    loader_result = load(run_id, layer3_dir, layer2_dir)
    selections = select_all(loader_result["evidence_bundles"], loader_result["spans_by_id"])

    total_selected = sum(s["counts"]["selected"] for s in selections)
    total_excluded = sum(s["counts"]["excluded"] for s in selections)
    print(f"\nSpan Selector — {run_id}")
    print(f"  Total selected : {total_selected}")
    print(f"  Total excluded : {total_excluded}")
    for sel in selections:
        c = sel["counts"]
        print(f"  {sel['story_title'][:50]:50s}  "
              f"sel={c['selected']}  excl={c['excluded']}  "
              f"signal={c['audience_signal']}")
