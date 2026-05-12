"""
Layer 4 — Module 10: Layer 4 Writer

Writes all Layer 4 output files to data/runs/{run_id}/layer_4/:
  atomic_claims.jsonl
  verified_claims.jsonl
  rejected_claims.jsonl
  claim_evidence_map.jsonl
  claim_dedup_groups.jsonl
  contradictions.json
  uncertainty_report.json
  evidence_density_report.json
  evidence_gaps.json
  story_fact_sheets.json
  layer4_manifest.json

Usage:
    Called by run_layer_4.py orchestrator.
"""

import sys
import json
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from config.time_utils import now_project_iso


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_jsonl(path: Path, records: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def write(
    run_id: str,
    layer4_dir: Path,
    layer3_dir: Path,
    layer2_dir: Path,
    verified_results: list[dict],
    contradiction_results: list[dict],
    density_results: list[dict],
    fact_sheets: list[dict],
    evidence_map_records: list[dict],
    dedup_groups: list[dict],
) -> dict:
    """
    Write all Layer 4 output files.
    Returns the layer4_manifest dict.
    """
    layer4_dir.mkdir(parents=True, exist_ok=True)
    now = now_project_iso()

    # ── Flatten claims ────────────────────────────────────────────────────────
    all_atomic:   list[dict] = []
    all_verified: list[dict] = []
    all_rejected: list[dict] = []

    for r in verified_results:
        for c in r.get("verified_claims", []):
            # Slim down for atomic_claims.jsonl
            all_atomic.append({
                "claim_id":             c["claim_id"],
                "story_id":             c["story_id"],
                "claim_text":           c["claim_text"],
                "claim_type":           c["claim_type"],
                "support_level":        c["support_level"],
                "source_span_ids":      c.get("evidence", {}).get("source_span_ids", []),
                "verification_status":  c["verification_status"],
            })
            # Full record for verified_claims.jsonl
            ev = c.get("evidence", {})
            all_verified.append({
                "claim_id":                  c["claim_id"],
                "story_id":                  c["story_id"],
                "claim_text":                c["claim_text"],
                "claim_type":                c["claim_type"],
                "verification_status":       c["verification_status"],
                "support_level":             c["support_level"],
                "confidence":                c["confidence_label"],
                "confidence_score":          c["confidence_score"],
                "requires_cautious_language": c.get("requires_cautious_language", False),
                "recommended_qualifier":     c.get("recommended_qualifier", ""),
                "source_span_ids":           ev.get("source_span_ids", []),
                "source_urls":               ev.get("source_urls", []),
                "trust_tiers":               ev.get("trust_tiers", []),
                "usable_in_script":          c.get("usable_in_script", False),
                "claim_importance":          c.get("claim_importance", "medium"),
            })
        for c in r.get("rejected_claims", []):
            all_atomic.append({
                "claim_id":            c["claim_id"],
                "story_id":            c["story_id"],
                "claim_text":          c["claim_text"],
                "claim_type":          c["claim_type"],
                "support_level":       c.get("support_level", "none"),
                "source_span_ids":     c.get("evidence", {}).get("source_span_ids", []),
                "verification_status": c["verification_status"],
            })
            all_rejected.append({
                "claim_id":        c["claim_id"],
                "story_id":        c["story_id"],
                "claim_text":      c["claim_text"],
                "verification_status": c["verification_status"],
                "rejection_reason": c.get("rejection_reason", "unsupported"),
                "required_action": "do_not_use",
            })

    # ── Write claim files ─────────────────────────────────────────────────────
    _write_jsonl(layer4_dir / "atomic_claims.jsonl",     all_atomic)
    _write_jsonl(layer4_dir / "verified_claims.jsonl",   all_verified)
    _write_jsonl(layer4_dir / "rejected_claims.jsonl",   all_rejected)
    _write_jsonl(layer4_dir / "claim_evidence_map.jsonl", evidence_map_records)
    _write_jsonl(layer4_dir / "claim_dedup_groups.jsonl", dedup_groups)

    # ── Contradictions ────────────────────────────────────────────────────────
    all_contradictions = []
    for entry in contradiction_results:
        all_contradictions.extend(entry.get("contradictions", []))
    _write_json(layer4_dir / "contradictions.json", {
        "run_id": run_id,
        "generated_at": now,
        "contradiction_count": len(all_contradictions),
        "contradictions": all_contradictions,
    })

    # ── Uncertainty report ────────────────────────────────────────────────────
    uncertain_claims = [
        {
            "claim_id":       c["claim_id"],
            "story_id":       c["story_id"],
            "claim_text":     c["claim_text"],
            "confidence":     c.get("confidence", ""),
            "confidence_score": c.get("confidence_score", 0.0),
            "uncertainty_reason": c.get("verification_status", ""),
            "recommended_qualifier": c.get("recommended_qualifier", ""),
        }
        for c in all_verified
        if c.get("verification_status") in ("uncertain", "partially_supported")
    ]
    _write_json(layer4_dir / "uncertainty_report.json", {
        "run_id": run_id,
        "generated_at": now,
        "uncertain_claim_count": len(uncertain_claims),
        "uncertain_claims": uncertain_claims,
    })

    # ── Evidence density report ───────────────────────────────────────────────
    density_stories = [
        {"story_id": d["story_id"], "story_title": d["story_title"], **d["density"]}
        for d in density_results
    ]
    _write_json(layer4_dir / "evidence_density_report.json", {
        "run_id": run_id,
        "generated_at": now,
        "stories": density_stories,
    })

    # ── Evidence gaps ─────────────────────────────────────────────────────────
    all_gaps = []
    for d in density_results:
        for gap in d.get("evidence_gaps", []):
            all_gaps.append({"story_id": d["story_id"], **gap})
    _write_json(layer4_dir / "evidence_gaps.json", {
        "run_id": run_id,
        "generated_at": now,
        "gap_count": len(all_gaps),
        "evidence_gaps": all_gaps,
    })

    # ── Story fact sheets ─────────────────────────────────────────────────────
    _write_json(layer4_dir / "story_fact_sheets.json", {
        "run_id": run_id,
        "generated_at": now,
        "story_count": len(fact_sheets),
        "story_fact_sheets": fact_sheets,
    })

    # ── Manifest ──────────────────────────────────────────────────────────────
    verified_count = len(all_verified)
    rejected_count = len(all_rejected)
    uncertain_count = len(uncertain_claims)
    deep_dive_ready = sum(1 for d in density_results if d["density"].get("safe_for_deep_dive"))
    roundup_ready   = sum(1 for d in density_results if d["density"].get("safe_for_roundup"))

    manifest = {
        "run_id":     run_id,
        "layer":      "layer_4_evidence_intelligence",
        "created_at": now,
        "inputs": {
            "story_clusters":       str(layer3_dir / "story_clusters.json"),
            "ranked_stories":       str(layer3_dir / "ranked_stories.json"),
            "source_spans":         str(layer2_dir / "source_spans.jsonl"),
            "canonical_documents":  str(layer2_dir / "canonical_documents.jsonl"),
            "layer3_manifest":      str(layer3_dir / "layer3_manifest.json"),
        },
        "outputs": {
            "atomic_claims":         str(layer4_dir / "atomic_claims.jsonl"),
            "verified_claims":       str(layer4_dir / "verified_claims.jsonl"),
            "rejected_claims":       str(layer4_dir / "rejected_claims.jsonl"),
            "claim_evidence_map":    str(layer4_dir / "claim_evidence_map.jsonl"),
            "claim_dedup_groups":    str(layer4_dir / "claim_dedup_groups.jsonl"),
            "contradictions":        str(layer4_dir / "contradictions.json"),
            "uncertainty_report":    str(layer4_dir / "uncertainty_report.json"),
            "evidence_density_report": str(layer4_dir / "evidence_density_report.json"),
            "evidence_gaps":         str(layer4_dir / "evidence_gaps.json"),
            "story_fact_sheets":     str(layer4_dir / "story_fact_sheets.json"),
        },
        "counts": {
            "stories_analyzed":       len(verified_results),
            "atomic_claims_extracted": len(all_atomic),
            "verified_claims":        verified_count,
            "rejected_claims":        rejected_count,
            "uncertain_claims":       uncertain_count,
            "contradictions":         len(all_contradictions),
            "evidence_gaps":          len(all_gaps),
            "dedup_groups":           len(dedup_groups),
        },
        "handoff": {
            "ready_for_layer_5":            roundup_ready > 0,
            "evidence_available_for_layer_6": verified_count > 0,
            "deep_dive_ready_stories":      deep_dive_ready,
            "roundup_ready_stories":        roundup_ready,
            "next_layer":                   "layer_5_editorial_intelligence",
        },
    }
    _write_json(layer4_dir / "layer4_manifest.json", manifest)
    return manifest
