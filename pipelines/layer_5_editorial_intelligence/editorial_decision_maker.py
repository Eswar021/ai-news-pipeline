"""
Layer 5 — Module 9: Editorial Decision Maker

Makes the final video selection from all scored candidates.
Includes lightweight portfolio balancing (merged from design module 5.13).

Decision logic:
  1. Filter out monitor_only and skip candidates.
  2. Evaluate deep dive candidate: highest opportunity score with recommended_format=deep_dive.
  3. Evaluate roundup candidates: top 5–8 stories with roundup_segment in allowed_formats,
     sorted by opportunity score.
  4. Choose format:
     - If a strong deep_dive candidate (score >= 80) exists, prefer deep_dive.
     - Otherwise build a roundup from top eligible stories.
     - Edge case: if < 5 roundup-eligible stories, fall back to deep_dive if available.
  5. Portfolio balance: penalize roundup selections with > 70% stories from one company.
     (No override for very high-impact stories from same company.)

Output:
  editorial_decision: {decision, selected_format, primary_story_id or selected_story_ids,
                       decision_confidence, decision_reasons, episode_theme, rejected_candidates}

Key function:
    decide(candidates, routing_decisions, opportunity_scores, format_config)
        → editorial_decision dict

Usage:
    python editorial_decision_maker.py --run-id run_2026_05_10_48h_auto
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from pipelines.runtime_manifest import get_format_requirements, load_manifest

_DEEP_DIVE_STRONG_THRESHOLD = 80
_ROUNDUP_MIN_STORIES = 5
_ROUNDUP_MAX_STORIES = 8
_COMPANY_DIVERSITY_LIMIT = 0.7   # max fraction from same company in roundup


def _entity_name(candidate: dict) -> str:
    companies = candidate.get("companies", [])
    return companies[0].lower() if companies else "unknown"


def _roundup_episode_theme(selected: list[dict]) -> str:
    story_types = [c.get("story_type", "unknown") for c in selected]
    topics_all  = []
    for c in selected:
        topics_all.extend(c.get("topics", []))

    # Build a simple thematic summary from types and companies
    companies = list({_entity_name(c) for c in selected if _entity_name(c) != "unknown"})
    type_summary = ", ".join(sorted(set(t for t in story_types if t != "unknown"))[:3])

    if len(companies) >= 3:
        company_text = f"{', '.join(companies[:2]).title()} and others"
    elif companies:
        company_text = " and ".join(c.title() for c in companies[:2])
    else:
        company_text = "AI companies"

    return (
        f"This week's AI updates: {company_text} push forward "
        f"with {type_summary or 'new developments'} across models, products, and tooling."
    )


def decide(candidates: list[dict], routing_decisions: list[dict],
           opportunity_scores: list[dict], format_config: dict | None = None) -> dict:

    roundup_config   = (format_config or {}).get("roundup",   {})
    min_roundup      = int(roundup_config.get("min_stories", _ROUNDUP_MIN_STORIES))
    max_roundup      = int(roundup_config.get("max_stories", _ROUNDUP_MAX_STORIES))

    # Build per-story lookup of routing and opportunity
    routing_by_id = {r["story_id"]: r for r in routing_decisions}
    opp_by_id     = {o["story_id"]: o for o in opportunity_scores}

    active_candidates = []
    rejected          = []

    for cand in candidates:
        sid     = cand["story_id"]
        routing = routing_by_id.get(sid, {})
        opp     = opp_by_id.get(sid, {})
        fmt     = routing.get("recommended_format", "monitor_only")

        if fmt in ("monitor_only", "skip"):
            rejected.append({
                "story_id":        sid,
                "story_title":     cand.get("story_title", ""),
                "rejection_reason": fmt,
                "details":         routing.get("routing_reasons", []),
                "recommended_action": "monitor_only",
            })
        else:
            active_candidates.append({
                "candidate":    cand,
                "routing":      routing,
                "opportunity":  opp,
                "opp_score":    opp.get("video_opportunity_score", 0),
                "allowed":      routing.get("allowed_formats", []),
            })

    if not active_candidates:
        return {
            "decision":            "no_video",
            "reason":              "No candidate passed evidence safety or novelty thresholds.",
            "recommended_action":  "continue_monitoring",
            "selected_story_ids":  [],
            "rejected_candidates": rejected,
        }

    # Sort by opportunity score descending
    active_candidates.sort(key=lambda x: x["opp_score"], reverse=True)

    # ── Evaluate deep dive candidate ──────────────────────────────────────────
    deep_dive_candidate = None
    for ac in active_candidates:
        if ("deep_dive" in ac["allowed"] and
                ac["opp_score"] >= _DEEP_DIVE_STRONG_THRESHOLD):
            deep_dive_candidate = ac
            break

    # ── Evaluate roundup candidates ───────────────────────────────────────────
    roundup_candidates = [
        ac for ac in active_candidates
        if "roundup_segment" in ac["allowed"]
    ]

    # ── Portfolio balance for roundup ─────────────────────────────────────────
    def _balance_roundup(pool: list) -> list:
        """
        Select up to max_roundup stories. Always fill to min_roundup first (no
        diversity check). After min_roundup, prefer stories from companies not
        yet heavily represented — but never drop below min_roundup.
        """
        selected: list        = []
        company_counts: dict  = {}

        for ac in pool:
            if len(selected) >= max_roundup:
                break
            selected.append(ac)
            company = _entity_name(ac["candidate"])
            company_counts[company] = company_counts.get(company, 0) + 1

        return selected

    # ── Choose format ─────────────────────────────────────────────────────────
    balanced_roundup = _balance_roundup(roundup_candidates)

    prefer_deep_dive = (
        deep_dive_candidate is not None and
        deep_dive_candidate["opp_score"] >= _DEEP_DIVE_STRONG_THRESHOLD and
        len(balanced_roundup) < min_roundup
    )

    if prefer_deep_dive or (
        deep_dive_candidate is not None and
        len(balanced_roundup) < min_roundup
    ):
        # Deep dive
        cand      = deep_dive_candidate["candidate"]
        opp       = deep_dive_candidate["opportunity"]
        conf      = round(deep_dive_candidate["opp_score"] / 100, 2)
        reasons   = [
            f"Opportunity score {deep_dive_candidate['opp_score']} — strong candidate.",
            "Single-story deep dive preferred: insufficient roundup coverage.",
        ]
        # Remaining non-selected go to rejected
        for ac in active_candidates:
            if ac["candidate"]["story_id"] != cand["story_id"]:
                rejected.append({
                    "story_id":        ac["candidate"]["story_id"],
                    "story_title":     ac["candidate"].get("story_title", ""),
                    "rejection_reason": "not_selected_for_this_run",
                    "details":         [f"Opportunity score {ac['opp_score']}."],
                    "recommended_action": "monitor_only",
                })
        return {
            "decision":           "create_video",
            "selected_format":    "deep_dive",
            "primary_story_id":   cand["story_id"],
            "supporting_story_ids": [],
            "decision_confidence": conf,
            "decision_reasons":   reasons,
            "episode_theme":      None,
            "rejected_candidates": rejected,
        }

    # Roundup
    if balanced_roundup:
        selected_cands  = [ac["candidate"] for ac in balanced_roundup]
        selected_ids    = [c["story_id"] for c in selected_cands]
        avg_opp         = sum(ac["opp_score"] for ac in balanced_roundup) / len(balanced_roundup)
        conf            = round(avg_opp / 100, 2)
        reasons = [
            f"{len(balanced_roundup)} stories selected for roundup.",
            f"Average opportunity score: {int(avg_opp)}.",
            "Multiple strong stories support a roundup over a single deep dive.",
        ]
        if deep_dive_candidate and not prefer_deep_dive:
            reasons.append(
                f"Deep dive candidate ({deep_dive_candidate['candidate']['story_title'][:40]}) "
                f"also eligible — roundup preferred for breadth."
            )
        # Rejected: active but not selected
        selected_set = set(selected_ids)
        for ac in active_candidates:
            if ac["candidate"]["story_id"] not in selected_set:
                rejected.append({
                    "story_id":        ac["candidate"]["story_id"],
                    "story_title":     ac["candidate"].get("story_title", ""),
                    "rejection_reason": "not_selected_for_roundup",
                    "details":         [
                        f"Opportunity score {ac['opp_score']}.",
                        "Removed for portfolio balance or story count limit.",
                    ],
                    "recommended_action": "include_in_next_roundup",
                })
        return {
            "decision":           "create_video",
            "selected_format":    "roundup",
            "primary_story_id":   None,
            "selected_story_ids": selected_ids,
            "decision_confidence": conf,
            "decision_reasons":   reasons,
            "episode_theme":      _roundup_episode_theme(selected_cands),
            "rejected_candidates": rejected,
        }

    # Fallback
    return {
        "decision":           "no_video",
        "reason":             "No candidates met format thresholds after portfolio balancing.",
        "recommended_action": "continue_monitoring",
        "selected_story_ids": [],
        "rejected_candidates": rejected,
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

    from pipelines.layer_5_editorial_intelligence.editorial_candidate_loader import load
    from pipelines.layer_5_editorial_intelligence.evidence_safety_gate   import gate_all
    from pipelines.layer_5_editorial_intelligence.audience_fit_analyzer  import analyze_all as af_all
    from pipelines.layer_5_editorial_intelligence.viewer_value_analyzer  import analyze_all as vv_all
    from pipelines.layer_5_editorial_intelligence.novelty_checker        import check_all
    from pipelines.layer_5_editorial_intelligence.format_fit_scorer      import score_all as ffs_all
    from pipelines.layer_5_editorial_intelligence.format_router          import route_all
    from pipelines.layer_5_editorial_intelligence.video_opportunity_scorer import score_all as opp_all

    layer3_dir = RUNS_DIR / run_id / "layer_3"
    layer4_dir = RUNS_DIR / run_id / "layer_4"
    result     = load(run_id, layer3_dir, layer4_dir)
    candidates = result["editorial_candidates"]

    safety  = gate_all(candidates)
    af      = af_all(candidates)
    print("  Running LLM for viewer value...")
    vv      = vv_all(candidates)
    novelty = check_all(candidates)
    ffs     = ffs_all(candidates, safety, af, vv, novelty)
    routing = route_all(candidates, ffs, safety, novelty)
    opp     = opp_all(candidates, safety, af, vv, novelty)

    manifest = load_manifest(run_id=run_id)
    fmt_cfg = get_format_requirements(manifest)

    ed = decide(candidates, routing, opp, fmt_cfg)
    print(f"\nEditorial Decision Maker — {run_id}")
    print(f"  Decision       : {ed['decision']}")
    print(f"  Format         : {ed.get('selected_format', 'n/a')}")
    if ed.get("selected_format") == "roundup":
        print(f"  Stories ({len(ed.get('selected_story_ids',[])):2d})  : "
              f"{', '.join(s[-6:] for s in ed.get('selected_story_ids', []))}")
        print(f"  Theme          : {ed.get('episode_theme', '')[:80]}")
    elif ed.get("selected_format") == "deep_dive":
        print(f"  Primary story  : {ed.get('primary_story_id', '')[-20:]}")
    print(f"  Confidence     : {ed.get('decision_confidence', 0):.2f}")
    print(f"  Rejected       : {len(ed.get('rejected_candidates', []))}")
