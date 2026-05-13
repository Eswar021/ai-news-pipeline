"""
Layer 4 — Module 7: Layer 4 Writer

Writes the lean Layer 4 artifact set.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.time_utils import now_project_iso


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def write(
    run_id: str,
    layer4_dir: Path,
    layer3_dir: Path,
    layer2_dir: Path,
    verified_results: list[dict],
    contradiction_results: list[dict],
    density_results: list[dict],
    fact_sheets: list[dict],
) -> dict:
    layer4_dir.mkdir(parents=True, exist_ok=True)
    now = now_project_iso()

    all_verified: list[dict] = []
    all_rejected: list[dict] = []
    extracted_claim_count = 0
    unresolved_provenance_count = 0

    for story_result in verified_results:
        extracted_claim_count += len(story_result.get("atomic_claims", []))
        for claim in story_result.get("verified_claims", []):
            all_verified.append(
                {
                    "claim_id": claim["claim_id"],
                    "story_id": claim["story_id"],
                    "claim_text": claim["claim_text"],
                    "claim_type": claim["claim_type"],
                    "verification_status": claim["verification_status"],
                    "support_level": claim["support_level"],
                    "confidence": claim["confidence_label"],
                    "confidence_score": claim["confidence_score"],
                    "requires_cautious_language": claim.get("requires_cautious_language", False),
                    "recommended_qualifier": claim.get("recommended_qualifier", ""),
                    "usable_in_script": claim.get("usable_in_script", False),
                    "source_span_ids": claim.get("source_span_ids", []),
                    "source_urls": claim.get("source_urls", []),
                    "canonical_document_ids": claim.get("canonical_document_ids", []),
                    "trust_tiers": claim.get("trust_tiers", []),
                    "source_roles": claim.get("source_roles", []),
                    "quote_anchor": claim.get("quote_anchor", ""),
                    "claim_importance": claim.get("claim_importance", "medium"),
                    "resolved_span_count": claim.get("resolved_span_count", 0),
                }
            )
            if claim.get("unresolved_provenance"):
                unresolved_provenance_count += 1

        for claim in story_result.get("rejected_claims", []):
            all_rejected.append(
                {
                    "claim_id": claim["claim_id"],
                    "story_id": claim["story_id"],
                    "claim_text": claim["claim_text"],
                    "claim_type": claim.get("claim_type", ""),
                    "verification_status": claim["verification_status"],
                    "rejection_reason": claim.get("rejection_reason", "unsupported"),
                    "required_action": "do_not_use",
                    "source_span_ids": claim.get("source_span_ids", []),
                    "source_urls": claim.get("source_urls", []),
                    "canonical_document_ids": claim.get("canonical_document_ids", []),
                    "quote_anchor": claim.get("quote_anchor", ""),
                }
            )
            if claim.get("unresolved_provenance"):
                unresolved_provenance_count += 1

    all_contradictions = []
    for entry in contradiction_results:
        all_contradictions.extend(entry.get("contradictions", []))

    density_stories = []
    all_gaps = []
    uncertainty_summary = {
        "uncertain_claim_count": 0,
        "high_confidence_count": 0,
    }
    for result in density_results:
        density_stories.append({"story_id": result["story_id"], "story_title": result["story_title"], **result["density"]})
        all_gaps.extend({"story_id": result["story_id"], **gap} for gap in result.get("evidence_gaps", []))
        summary = result.get("uncertainty_summary", {})
        uncertainty_summary["uncertain_claim_count"] += int(summary.get("uncertain_claim_count", 0))
        uncertainty_summary["high_confidence_count"] += int(summary.get("high_confidence_count", 0))

    _write_jsonl(layer4_dir / "verified_claims.jsonl", all_verified)
    _write_jsonl(layer4_dir / "rejected_claims.jsonl", all_rejected)
    _write_json(layer4_dir / "contradictions.json", {
        "run_id": run_id,
        "generated_at": now,
        "contradiction_count": len(all_contradictions),
        "contradictions": all_contradictions,
    })
    _write_json(layer4_dir / "evidence_density_report.json", {
        "run_id": run_id,
        "generated_at": now,
        "stories": density_stories,
        "uncertainty_summary": uncertainty_summary,
    })
    _write_json(layer4_dir / "evidence_gaps.json", {
        "run_id": run_id,
        "generated_at": now,
        "gap_count": len(all_gaps),
        "evidence_gaps": all_gaps,
    })
    _write_json(layer4_dir / "story_fact_sheets.json", {
        "run_id": run_id,
        "generated_at": now,
        "story_count": len(fact_sheets),
        "story_fact_sheets": fact_sheets,
    })

    roundup_ready = sum(1 for result in density_results if result["density"].get("safe_for_roundup"))
    deep_dive_ready = sum(1 for result in density_results if result["density"].get("safe_for_deep_dive"))
    manifest = {
        "run_id": run_id,
        "layer": "layer_4_evidence_intelligence",
        "created_at": now,
        "inputs": {
            "story_clusters": str(layer3_dir / "story_clusters.json"),
            "ranked_stories": str(layer3_dir / "ranked_stories.json"),
            "source_spans": str(layer2_dir / "source_spans.jsonl"),
            "canonical_documents": str(layer2_dir / "canonical_documents.jsonl"),
            "layer3_manifest": str(layer3_dir / "layer3_manifest.json"),
        },
        "outputs": {
            "verified_claims": str(layer4_dir / "verified_claims.jsonl"),
            "rejected_claims": str(layer4_dir / "rejected_claims.jsonl"),
            "contradictions": str(layer4_dir / "contradictions.json"),
            "evidence_density_report": str(layer4_dir / "evidence_density_report.json"),
            "evidence_gaps": str(layer4_dir / "evidence_gaps.json"),
            "story_fact_sheets": str(layer4_dir / "story_fact_sheets.json"),
        },
        "counts": {
            "stories_analyzed": len(verified_results),
            "atomic_claims_extracted": extracted_claim_count,
            "verified_claims": len(all_verified),
            "rejected_claims": len(all_rejected),
            "contradictions": len(all_contradictions),
            "evidence_gaps": len(all_gaps),
            "unresolved_provenance_claims": unresolved_provenance_count,
        },
        "handoff": {
            "ready_for_layer_5": roundup_ready > 0,
            "evidence_available_for_layer_6": len(all_verified) > 0,
            "deep_dive_ready_stories": deep_dive_ready,
            "roundup_ready_stories": roundup_ready,
            "next_layer": "layer_5_editorial_intelligence",
        },
    }
    _write_json(layer4_dir / "layer4_manifest.json", manifest)
    return manifest
