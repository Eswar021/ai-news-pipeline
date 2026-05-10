"""
Layer 4 — Module 1: Story Evidence Loader

Loads Layer 3 story clusters + Layer 2 source spans/docs for every story
recommended for Layer 4 analysis.

Builds one evidence bundle per story, separating spans by source role:
  primary_evidence_spans   — tier 1 official/company blogs
  secondary_evidence_spans — tier 2 news / cross-references
  research_evidence_spans  — arxiv / research papers
  technical_artifact_spans — github, notebooks, technical docs
  trend_signal_spans       — HN, Reddit, community posts

Key function:
    load(run_id, layer3_dir, layer2_dir, max_stories=15)
        → {stories_loaded, evidence_bundles, docs_by_id, spans_by_id, counts}

Usage:
    python evidence_loader.py --run-id run_2026_05_10_48h_auto
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_PRIMARY_ROLES   = {"primary_evidence", "company_blog", "official_announcement"}
_SECONDARY_ROLES = {"secondary_evidence", "cross_reference", "industry_news", "news_coverage"}
_RESEARCH_ROLES  = {"research_paper", "arxiv_paper", "academic_paper"}
_TECHNICAL_ROLES = {"technical_artifact", "github_repo", "technical_doc", "code_artifact"}
_TREND_ROLES     = {"community_signal", "social_mention", "forum_post",
                    "youtube_transcript", "community_discussion"}


def _classify_span(span: dict) -> str:
    role = span.get("source_role", "")
    tier = span.get("trust_tier", 4)
    if role in _RESEARCH_ROLES:
        return "research_evidence_spans"
    if role in _TECHNICAL_ROLES:
        return "technical_artifact_spans"
    if role in _TREND_ROLES:
        return "trend_signal_spans"
    if tier <= 1.5 or role in _PRIMARY_ROLES:
        return "primary_evidence_spans"
    if tier <= 2.5 or role in _SECONDARY_ROLES:
        return "secondary_evidence_spans"
    return "trend_signal_spans"


def load(run_id: str, layer3_dir: Path, layer2_dir: Path, max_stories: int = 15) -> dict:
    """
    Build evidence bundles for all Layer 4 stories.

    Returns:
        {
          "stories_loaded": int,
          "evidence_bundles": [EvidenceBundle, ...],
          "docs_by_id": {doc_id: doc},
          "spans_by_id": {span_id: span},
          "counts": {...}
        }
    """
    # ── Load Layer 3 outputs ─────────────────────────────────────────────────
    ranked_stories = json.loads((layer3_dir / "ranked_stories.json").read_text())["ranked_stories"]
    l4_ranked = [r for r in ranked_stories if r.get("recommended_for_layer_4")][:max_stories]
    l4_story_ids = {r["story_id"] for r in l4_ranked}

    clusters_raw = json.loads((layer3_dir / "story_clusters.json").read_text())["story_clusters"]
    cluster_by_id = {c["story_id"]: c for c in clusters_raw}

    # ── Load Layer 2 canonical documents ────────────────────────────────────
    docs_by_id: dict = {}
    for line in (layer2_dir / "canonical_documents.jsonl").read_text().splitlines():
        if line.strip():
            doc = json.loads(line)
            docs_by_id[doc["canonical_document_id"]] = doc

    # ── Load all source spans ────────────────────────────────────────────────
    spans_by_id: dict = {}
    for line in (layer2_dir / "source_spans.jsonl").read_text().splitlines():
        if line.strip():
            sp = json.loads(line)
            spans_by_id[sp["span_id"]] = sp

    # ── Build evidence bundles ───────────────────────────────────────────────
    evidence_bundles = []
    total_spans_loaded = 0
    missing_spans = 0

    for ranked in l4_ranked:
        sid = ranked["story_id"]
        cluster = cluster_by_id.get(sid)
        if not cluster:
            continue

        bundle_spans: dict[str, list] = {
            "primary_evidence_spans": [],
            "secondary_evidence_spans": [],
            "research_evidence_spans": [],
            "technical_artifact_spans": [],
            "trend_signal_spans": [],
        }

        for span_id in cluster["cluster_members"]["source_span_ids"]:
            sp = spans_by_id.get(span_id)
            if not sp:
                missing_spans += 1
                continue
            bucket = _classify_span(sp)
            bundle_spans[bucket].append(span_id)
            total_spans_loaded += 1

        member_docs = [
            docs_by_id[did]
            for did in cluster["cluster_members"]["canonical_document_ids"]
            if did in docs_by_id
        ]

        evidence_bundles.append({
            "story_id":    sid,
            "story_title": ranked["story_title"],
            "story_type":  ranked["story_type"],
            "rank":        ranked["rank"],
            "total_story_score": ranked["total_story_score"],
            "cluster":     cluster,
            "member_docs": member_docs,
            "evidence_spans": bundle_spans,
            "span_counts": {k: len(v) for k, v in bundle_spans.items()},
            "total_spans": sum(len(v) for v in bundle_spans.values()),
        })

    return {
        "stories_loaded":   len(evidence_bundles),
        "evidence_bundles": evidence_bundles,
        "docs_by_id":       docs_by_id,
        "spans_by_id":      spans_by_id,
        "counts": {
            "stories_selected":   len(l4_story_ids),
            "total_spans_loaded": total_spans_loaded,
            "missing_spans":      missing_spans,
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
            if (rp.parent / "layer_3" / "ranked_stories.json").exists():
                run_id = rp.parent.name
                break
        print(f"Auto-discovered run: {run_id}")

    layer3_dir = RUNS_DIR / run_id / "layer_3"
    layer2_dir = RUNS_DIR / run_id / "layer_2"
    result = load(run_id, layer3_dir, layer2_dir)

    print(f"\nEvidence Loader — {run_id}")
    print(f"  Stories loaded : {result['stories_loaded']}")
    print(f"  Total spans    : {result['counts']['total_spans_loaded']}")
    print(f"  Missing spans  : {result['counts']['missing_spans']}")
    for bundle in result["evidence_bundles"]:
        sc = bundle["span_counts"]
        print(f"  [{bundle['rank']:2}] {bundle['story_title'][:45]:45s} "
              f"pri={sc['primary_evidence_spans']} "
              f"sec={sc['secondary_evidence_spans']} "
              f"res={sc['research_evidence_spans']} "
              f"trend={sc['trend_signal_spans']}")
