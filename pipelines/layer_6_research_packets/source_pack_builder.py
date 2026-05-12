"""
Layer 6 — Module 5: Source Pack Builder

Resolves all claim IDs used in the packet to their backing sources.

Data join chain:
  claim_id → claim_evidence_map → source_span_ids
           → source_spans → canonical_document_id
           → canonical_documents → title, URL, publisher, trust_tier

Deduplicates by canonical_url. Marks trust_tier=1 sources as
recommended_for_youtube_description.

Key function:
    build(all_claim_ids, evidence_map_by_id, spans_by_id, docs_by_id) → source_pack dict

Individual test:
    python source_pack_builder.py
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from config.time_utils import now_project_iso

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_SOURCE_ROLE_ORDER = [
    "primary_evidence",
    "independent_media",
    "research",
    "technical_artifact",
    "video_transcript",
    "community_signal",
    "trend_signal_only",
]


def build(
    all_claim_ids:      set,
    evidence_map_by_id: dict,
    spans_by_id:        dict,
    docs_by_id:         dict,
    run_id:             str = "",
) -> dict:
    # claim_id → {doc_id → {span_ids, claim_ids}}
    doc_to_data: dict[str, dict] = {}

    for cid in all_claim_ids:
        em = evidence_map_by_id.get(cid, {})
        for span_id in em.get("source_span_ids", []):
            span  = spans_by_id.get(span_id, {})
            doc_id = span.get("canonical_document_id", "")
            if not doc_id:
                continue
            if doc_id not in doc_to_data:
                doc_to_data[doc_id] = {"span_ids": set(), "claim_ids": set()}
            doc_to_data[doc_id]["span_ids"].add(span_id)
            doc_to_data[doc_id]["claim_ids"].add(cid)

    # Deduplicate by canonical_url; build source list
    seen_urls: dict[str, str] = {}   # url → doc_id (keep first)
    sources = []

    for doc_id, data in doc_to_data.items():
        doc  = docs_by_id.get(doc_id, {})
        url  = doc.get("canonical_url") or doc.get("original_url", "")
        if url in seen_urls:
            # Merge claims/spans into already-added source
            for existing in sources:
                if existing["canonical_document_id"] == seen_urls[url]:
                    existing["supports_claim_ids"] = list(
                        set(existing["supports_claim_ids"]) | data["claim_ids"]
                    )
                    existing["source_span_ids"] = list(
                        set(existing["source_span_ids"]) | data["span_ids"]
                    )
            continue
        seen_urls[url] = doc_id

        trust_tier  = doc.get("trust_tier", 3)
        source_role = doc.get("source_role", "unknown")

        sources.append({
            "source_ref_id":                  f"source_{doc_id[-8:]}",
            "canonical_document_id":          doc_id,
            "source_name":                    doc.get("source_name", ""),
            "source_role":                    source_role,
            "trust_tier":                     trust_tier,
            "title":                          doc.get("title", ""),
            "canonical_url":                  url,
            "publisher":                      doc.get("publisher", ""),
            "published_at":                   doc.get("published_at", ""),
            "supports_claim_ids":             sorted(data["claim_ids"]),
            "source_span_ids":                sorted(data["span_ids"]),
            "recommended_for_youtube_description": trust_tier == 1,
        })

    # Sort: trust_tier asc, then by source_role priority
    role_rank = {r: i for i, r in enumerate(_SOURCE_ROLE_ORDER)}
    sources.sort(key=lambda s: (s["trust_tier"], role_rank.get(s["source_role"], 99)))

    now = now_project_iso()
    source_pack_id = f"source_pack_{now[:10].replace('-', '')}"

    return {
        "source_pack_id":        source_pack_id,
        "run_id":                run_id,
        "generated_at":          now,
        "source_count":          len(sources),
        "recommended_count":     sum(1 for s in sources if s["recommended_for_youtube_description"]),
        "sources":               sources,
    }


if __name__ == "__main__":
    from pipelines.layer_6_research_packets.brief_loader           import load as load_brief
    from pipelines.layer_6_research_packets.roundup_packet_builder  import build as build_roundup
    from pipelines.layer_6_research_packets.evidence_boundary_enforcer import enforce

    run_id     = sorted(RUNS_DIR.glob("*/layer_5/selected_video_brief.json"),
                        key=lambda p: p.stat().st_mtime, reverse=True)[0].parents[1].name
    layer2_dir = RUNS_DIR / run_id / "layer_2"
    layer4_dir = RUNS_DIR / run_id / "layer_4"
    layer5_dir = RUNS_DIR / run_id / "layer_5"

    brief_ctx = load_brief(layer5_dir)

    with open(layer4_dir / "story_fact_sheets.json") as f:
        raw = json.load(f)
    fact_sheets_by_id = {fs["story_id"]: fs for fs in raw["story_fact_sheets"]}

    claims_by_id = {}
    with open(layer4_dir / "verified_claims.jsonl") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                claims_by_id[c["claim_id"]] = c

    evidence_map_by_id = {}
    with open(layer4_dir / "claim_evidence_map.jsonl") as f:
        for line in f:
            if line.strip():
                em = json.loads(line)
                evidence_map_by_id[em["claim_id"]] = em

    spans_by_id = {}
    with open(layer2_dir / "source_spans.jsonl") as f:
        for line in f:
            if line.strip():
                s = json.loads(line)
                spans_by_id[s["span_id"]] = s

    docs_by_id = {}
    with open(layer2_dir / "canonical_documents.jsonl") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                docs_by_id[d["canonical_document_id"]] = d

    packet      = build_roundup(brief_ctx, fact_sheets_by_id, claims_by_id)
    b_report    = enforce(packet, brief_ctx, claims_by_id)
    all_cids    = brief_ctx["safe_claim_ids"] | brief_ctx["cautious_claim_ids"]
    source_pack = build(all_cids, evidence_map_by_id, spans_by_id, docs_by_id, run_id)

    print(f"Sources total       : {source_pack['source_count']}")
    print(f"Recommended (YT)    : {source_pack['recommended_count']}")
    print()
    for src in source_pack["sources"][:5]:
        print(f"  [{src['trust_tier']}] {src['source_role']:25s} | {src['publisher']:20s} | claims={len(src['supports_claim_ids'])}")
        print(f"       Title: {src['title'][:70]}")
        print(f"       URL  : {src['canonical_url'][:80]}")
        print()
