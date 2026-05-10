"""
Layer 5 — Module 1: Editorial Candidate Loader

Joins Layer 3 story data with Layer 4 evidence data to build
EditorialCandidate objects for editorial scoring.

Data sources:
  Layer 3: ranked_stories.json, story_entity_topic_map.json
  Layer 4: story_fact_sheets.json, evidence_density_report.json,
           evidence_gaps.json

Key function:
    load(run_id, layer3_dir, layer4_dir) → {editorial_candidates, counts}

Usage:
    python editorial_candidate_loader.py --run-id run_2026_05_10_48h_auto
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR


def _candidate_id(story_id: str) -> str:
    parts = story_id.split("_")
    suffix = parts[-1] if len(parts[-1]) >= 4 else story_id[-8:]
    return f"candidate_{suffix}"


def load(run_id: str, layer3_dir: Path, layer4_dir: Path) -> dict:
    """
    Build EditorialCandidate objects by joining L3 story rankings with L4 evidence.
    Only stories that have Layer 4 fact sheets are included.
    """
    # ── Load Layer 3 ─────────────────────────────────────────────────────────
    with open(layer3_dir / "ranked_stories.json") as f:
        ranked_raw = json.load(f)
    ranked_by_id = {s["story_id"]: s for s in ranked_raw["ranked_stories"]}

    with open(layer3_dir / "story_entity_topic_map.json") as f:
        etm_raw = json.load(f)
    etm_by_id = {
        entry["story_id"]: entry
        for entry in etm_raw["story_entity_topic_map"]
    }

    # ── Load Layer 4 ─────────────────────────────────────────────────────────
    with open(layer4_dir / "story_fact_sheets.json") as f:
        fs_raw = json.load(f)
    # Keyed by story_id — fact sheets are the source of truth for which stories L4 processed
    sheets_by_id = {s["story_id"]: s for s in fs_raw["story_fact_sheets"]}

    with open(layer4_dir / "evidence_density_report.json") as f:
        edr_raw = json.load(f)
    density_by_id = {r["story_id"]: r for r in edr_raw["stories"]}

    with open(layer4_dir / "evidence_gaps.json") as f:
        gaps_raw = json.load(f)
    # Group gaps by story_id
    gaps_by_id: dict[str, list] = {}
    for gap in gaps_raw["evidence_gaps"]:
        gaps_by_id.setdefault(gap["story_id"], []).append(gap)

    # ── Build candidates (L4 fact sheets define the set) ─────────────────────
    candidates: list[dict] = []

    for story_id, sheet in sheets_by_id.items():
        ranked = ranked_by_id.get(story_id, {})
        density = density_by_id.get(story_id, {})
        etm = etm_by_id.get(story_id, {})
        gaps = gaps_by_id.get(story_id, [])

        entities = etm.get("entities", {})
        topics = etm.get("topics", [])

        safe_facts = sheet.get("safe_facts", [])
        cautious_facts = sheet.get("cautious_facts", [])
        do_not_use = sheet.get("do_not_use", [])

        blocking_gaps = [g for g in gaps if g.get("blocks_roundup") or g.get("blocks_deep_dive")]

        candidate = {
            "editorial_candidate_id": _candidate_id(story_id),
            "run_id":                 run_id,
            "story_id":               story_id,
            "story_title":            ranked.get("story_title") or sheet.get("canonical_story_title", ""),
            "story_type":             ranked.get("story_type", ""),
            "rank":                   ranked.get("rank", 99),
            "total_story_score":      ranked.get("total_story_score", 0),
            "ranking_bucket":         ranked.get("ranking_bucket", "unknown"),
            # Evidence from L4 density
            "verified_claim_count":   density.get("verified_claim_count", 0),
            "evidence_density_score": density.get("evidence_density_score", 0),
            "primary_source_count":   density.get("primary_source_count", 0),
            "independent_source_count": density.get("independent_source_count", 0),
            "safe_for_roundup":       density.get("safe_for_roundup", False),
            "safe_for_deep_dive":     density.get("safe_for_deep_dive", False),
            "high_sev_contradictions": density.get("high_sev_contradictions", 0),
            "format_suitability":     density.get("format_suitability", ""),
            # Claims from fact sheet
            "safe_claim_ids":         [c["claim_id"] for c in safe_facts],
            "cautious_claim_ids":     [c["claim_id"] for c in cautious_facts],
            "do_not_use_claim_ids":   [c["claim_id"] for c in do_not_use],
            "safe_facts":             safe_facts,      # full objects for LLM
            # Entities and topics from L3 entity map
            "companies":              entities.get("companies", []),
            "models":                 entities.get("models", []),
            "products":               entities.get("products", []),
            "topics":                 topics,
            # Gap info
            "evidence_gap_count":     len(gaps),
            "blocking_gaps":          blocking_gaps,
            "candidate_status":       "ready_for_editorial_evaluation",
        }
        candidates.append(candidate)

    # Sort by rank
    candidates.sort(key=lambda c: c["rank"])

    return {
        "run_id":              run_id,
        "editorial_candidates": candidates,
        "counts": {
            "total_candidates":    len(candidates),
            "with_primary_source": sum(1 for c in candidates if c["primary_source_count"] > 0),
            "deep_dive_eligible":  sum(1 for c in candidates if c["safe_for_deep_dive"]),
            "roundup_eligible":    sum(1 for c in candidates if c["safe_for_roundup"]),
        },
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
            if (rp.parent / "layer_4" / "story_fact_sheets.json").exists():
                run_id = rp.parent.name
                break
        print(f"Auto-discovered run: {run_id}")

    layer3_dir = RUNS_DIR / run_id / "layer_3"
    layer4_dir = RUNS_DIR / run_id / "layer_4"
    result = load(run_id, layer3_dir, layer4_dir)

    candidates = result["editorial_candidates"]
    c = result["counts"]
    print(f"\nEditorial Candidate Loader — {run_id}")
    print(f"  Total candidates   : {c['total_candidates']}")
    print(f"  Roundup eligible   : {c['roundup_eligible']}")
    print(f"  Deep-dive eligible : {c['deep_dive_eligible']}")
    print(f"  With primary source: {c['with_primary_source']}")
    print()
    for cand in candidates:
        print(f"  [{cand['rank']:2d}] {cand['story_title'][:50]:50s}  "
              f"type={cand['story_type']:<22}  "
              f"claims={cand['verified_claim_count']:2d}  "
              f"density={cand['evidence_density_score']}")
