"""
Layer 9 — Module 16: Layer 9 Output Writer

Writes all Layer 9 output files to layer_9/ and returns manifest dict.

Output files:
  verification_report.json
  sentence_verification_results.jsonl
  unsupported_sentences.jsonl
  overclaim_report.json
  cautious_language_verification.json
  rejected_claim_leakage_report.json
      contradiction_handling_report.json
      repetition_safety_report.json
      metadata_safety_report.json
  source_attribution_report.json
  correction_patch.json
  verified_script.md
  verified_youtube_metadata.json
  final_publish_package.json
  layer9_manifest.json

Key function:
    write(...) → manifest dict
"""

import json
from datetime import datetime, timezone
from config.time_utils import now_project_iso
from pathlib import Path


def _write_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _write_jsonl(path: Path, records: list):
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def write(
    run_id:              str,
    layer9_dir:          Path,
    layer8_dir:          Path,
    layer7_dir:          Path,
    layer4_dir:          Path,
    layer2_dir:          Path,
    ctx:                 dict,
    classified:          list,
    coverage_result:     dict,
    traceability_result: dict,
    support_results:     list,
    overclaim_result:    dict,
    cautious_result:     dict,
    leakage_result:      dict,
    contradiction_result: dict,
    repetition_result:   dict,
    metadata_result:     dict,
    attribution_result:  dict,
    risk_result:         dict,
    patch_result:        dict,
    verified_script:     dict,
    structure_result:    dict,
) -> dict:
    layer9_dir.mkdir(parents=True, exist_ok=True)
    now = now_project_iso()

    gs  = ctx["generated_script"]
    yt  = ctx["youtube_metadata"]
    rec = risk_result.get("final_recommendation", "approved_with_warnings")

    # ── verification_report.json ──────────────────────────────────────────────
    _write_json(layer9_dir / "verification_report.json", {
        "run_id":       run_id,
        "layer":        "layer_9_verification_firewall",
        "generated_at": now,
        "summary": {
            "final_status":              rec,
            "overall_risk_level":        risk_result["overall_risk_level"],
            "risk_score":                risk_result["risk_score"],
            "sentence_count":            len(ctx["sentence_list"]),
            "sentences_needing_support": sum(1 for s in classified if s.get("requires_claim_support")),
            "covered_sentences":         coverage_result["covered"],
            "analysis_only_sentences":   coverage_result["analysis_only"],
            "uncovered_sentences":       coverage_result["uncovered"],
            "critical_issue_count":      risk_result["critical_count"],
            "high_issue_count":          risk_result["high_count"],
            "medium_issue_count":        risk_result["medium_count"],
            "overclaim_count":           overclaim_result["overclaim_count"],
            "leaks_found":               leakage_result["leak_count"],
            "repetition_issue_count":    repetition_result.get("issue_count", 0),
        },
        "checks": {
            "script_structure":        structure_result.get("status", "passed"),
            "sentence_coverage":       "passed" if coverage_result["passed"] else "failed",
            "claim_traceability":      "passed" if traceability_result["passed"] else "failed",
            "sentence_support":        "passed" if not any(
                r["support_status"] in ("overclaim", "unsupported") for r in support_results) else "failed",
            "overclaim_detector":      "passed" if overclaim_result["passed"] else "failed",
            "cautious_language":       "passed" if cautious_result["passed"] else "failed",
            "rejected_claim_leakage":  "passed" if leakage_result["passed"] else "failed",
            "repetition_safety":       repetition_result.get("status", "passed"),
            "metadata_safety":         metadata_result.get("status", "passed"),
            "source_attribution":      "passed" if attribution_result["passed"] else "failed",
        },
        "decision": {
            "ready_for_human_review": rec in ("approved", "approved_with_warnings"),
            "ready_for_layer_10":     rec in ("approved", "approved_with_warnings"),
            "ready_for_publish":      False,
            "revision_required":      rec in ("requires_revision", "blocked"),
            "reason":                 f"{rec} — see priority_fixes for details.",
        },
        "priority_fixes": risk_result.get("priority_fixes", []),
    })

    # ── sentence_verification_results.jsonl ───────────────────────────────────
    sup_by_id = {r["sentence_id"]: r for r in support_results}
    cov_by_id = {r["sentence_id"]: r for r in coverage_result["results"]}
    sv_records = []
    for sent in classified:
        sid = sent["sentence_id"]
        cov = cov_by_id.get(sid, {})
        sup = sup_by_id.get(sid, {})
        sv_records.append({
            "sentence_id":        sid,
            "section_key":        sent.get("section_key", ""),
            "sentence_text":      sent.get("sentence_text", ""),
            "verified_type":      sent.get("verified_sentence_type", ""),
            "requires_support":   sent.get("requires_claim_support", False),
            "claim_ids":          sent.get("claim_ids", []),
            "coverage_status":    cov.get("coverage_status", ""),
            "support_status":     sup.get("support_status", ""),
            "severity":           sup.get("severity", cov.get("severity", "info")),
            "issue":              sup.get("issue"),
            "recommended_fix":    sup.get("recommended_fix"),
        })
    _write_jsonl(layer9_dir / "sentence_verification_results.jsonl", sv_records)

    # ── unsupported_sentences.jsonl ───────────────────────────────────────────
    unsupported = [
        r for r in support_results
        if r.get("support_status") in ("overclaim", "unsupported")
    ] + coverage_result.get("uncovered_list", [])
    _write_jsonl(layer9_dir / "unsupported_sentences.jsonl", unsupported)

    # ── overclaim_report.json ─────────────────────────────────────────────────
    _write_json(layer9_dir / "overclaim_report.json", {
        "run_id":          run_id,
        "generated_at":    now,
        "overclaim_count": overclaim_result["overclaim_count"],
        "overclaims":      overclaim_result["overclaims"],
        "llm_issues":      [r for r in support_results if r.get("support_status") == "overclaim"],
    })

    # ── cautious_language_verification.json ───────────────────────────────────
    _write_json(layer9_dir / "cautious_language_verification.json", {
        "run_id":       run_id,
        "generated_at": now,
        **cautious_result,
    })

    # ── rejected_claim_leakage_report.json ────────────────────────────────────
    _write_json(layer9_dir / "rejected_claim_leakage_report.json", {
        "run_id":       run_id,
        "generated_at": now,
        **leakage_result,
    })

    # ── contradiction_handling_report.json ────────────────────────────────────
    _write_json(layer9_dir / "contradiction_handling_report.json", {
        "run_id":       run_id,
        "generated_at": now,
        **contradiction_result,
    })

    # ── repetition_safety_report.json ─────────────────────────────────────────
    _write_json(layer9_dir / "repetition_safety_report.json", {
        "run_id":       run_id,
        "generated_at": now,
        **repetition_result,
    })

    # ── metadata_safety_report.json ───────────────────────────────────────────
    _write_json(layer9_dir / "metadata_safety_report.json", {
        "run_id":       run_id,
        "generated_at": now,
        **metadata_result,
    })

    # ── source_attribution_report.json ────────────────────────────────────────
    _write_json(layer9_dir / "source_attribution_report.json", {
        "run_id":       run_id,
        "generated_at": now,
        **attribution_result,
    })

    # ── correction_patch.json ─────────────────────────────────────────────────
    _write_json(layer9_dir / "correction_patch.json", {
        "run_id":       run_id,
        "generated_at": now,
        **patch_result,
    })

    # ── verified_script.md ────────────────────────────────────────────────────
    if verified_script["status"] == "created" and verified_script["verified_script_text"]:
        (layer9_dir / "verified_script.md").write_text(
            verified_script["verified_script_text"], encoding="utf-8"
        )
    else:
        (layer9_dir / "verified_script.md").write_text(
            f"# Verified Script Not Created\n\nReason: {verified_script.get('reason', 'unknown')}\n",
            encoding="utf-8",
        )

    # ── verified_youtube_metadata.json ────────────────────────────────────────
    approved_titles = [
        t for t in metadata_result.get("title_checks", [])
        if t.get("status") in ("safe", "soft_warning")
    ]
    _write_json(layer9_dir / "verified_youtube_metadata.json", {
        "run_id":              run_id,
        "generated_at":        now,
        "recommended_title":   approved_titles[0]["title"] if approved_titles else "",
        "approved_titles":     approved_titles,
        "approved_thumbnails": [t for t in metadata_result.get("thumbnail_checks", []) if t["status"] == "safe"],
        "chapters":            yt.get("chapters", []),
        "description":         yt.get("description", ""),
        "source_list":         yt.get("source_list", []),
        "tags":                yt.get("tags", []),
    })

    # ── final_publish_package.json ────────────────────────────────────────────
    _write_json(layer9_dir / "final_publish_package.json", {
        "run_id":       run_id,
        "generated_at": now,
        "approval": {
            "status":                 rec,
            "ready_for_human_review": rec in ("approved", "approved_with_warnings"),
            "ready_for_publish":      False,
            "reason":                 "Final publishing is a manual decision.",
        },
        "assets": {
            "verified_script":    str(layer9_dir / "verified_script.md"),
            "youtube_metadata":   str(layer9_dir / "verified_youtube_metadata.json"),
            "verification_report": str(layer9_dir / "verification_report.json"),
            "correction_patch":   str(layer9_dir / "correction_patch.json"),
        },
        "summary": {
            "selected_format":       gs.get("selected_format", ""),
            "estimated_duration_s":  gs.get("estimated_seconds", 0),
            "risk_level":            risk_result["overall_risk_level"],
            "risk_score":            risk_result["risk_score"],
            "patches_applied":       verified_script.get("patches_applied_count", 0),
            "remaining_warnings":    verified_script.get("remaining_warnings", 0),
        },
        "memory_handoff": {
            "ready_for_layer_10":     rec in ("approved", "approved_with_warnings"),
            "memory_update_allowed":  True,
            "memory_update_scope": [
                "published_video_candidate",
                "used_claims",
                "source_usage",
                "title_options",
                "topic_coverage",
            ],
        },
    })

    # ── layer9_manifest.json ──────────────────────────────────────────────────
    manifest = {
        "run_id":       run_id,
        "layer":        "layer_9_verification_firewall",
        "created_at":   now,
        "inputs": {
            "script_md":           str(layer8_dir / "script.md"),
            "sentence_claim_map":  str(layer8_dir / "sentence_claim_map.jsonl"),
            "verified_claims":     str(layer4_dir / "verified_claims.jsonl"),
            "rejected_claims":     str(layer4_dir / "rejected_claims.jsonl"),
            "source_spans":        str(layer2_dir / "source_spans.jsonl"),
        },
        "outputs": {
            "verification_report":             str(layer9_dir / "verification_report.json"),
            "sentence_verification_results":   str(layer9_dir / "sentence_verification_results.jsonl"),
            "unsupported_sentences":           str(layer9_dir / "unsupported_sentences.jsonl"),
            "overclaim_report":                str(layer9_dir / "overclaim_report.json"),
            "cautious_language_verification":  str(layer9_dir / "cautious_language_verification.json"),
            "rejected_claim_leakage_report":   str(layer9_dir / "rejected_claim_leakage_report.json"),
            "contradiction_handling_report":   str(layer9_dir / "contradiction_handling_report.json"),
            "repetition_safety_report":        str(layer9_dir / "repetition_safety_report.json"),
            "metadata_safety_report":          str(layer9_dir / "metadata_safety_report.json"),
            "source_attribution_report":       str(layer9_dir / "source_attribution_report.json"),
            "correction_patch":                str(layer9_dir / "correction_patch.json"),
            "verified_script":                 str(layer9_dir / "verified_script.md"),
            "verified_youtube_metadata":       str(layer9_dir / "verified_youtube_metadata.json"),
            "final_publish_package":           str(layer9_dir / "final_publish_package.json"),
            "layer9_manifest":                 str(layer9_dir / "layer9_manifest.json"),
        },
        "verification_summary": {
            "final_status":              rec,
            "overall_risk_level":        risk_result["overall_risk_level"],
            "risk_score":                risk_result["risk_score"],
            "sentence_count":            len(ctx["sentence_list"]),
            "critical_issue_count":      risk_result["critical_count"],
            "high_issue_count":          risk_result["high_count"],
            "medium_issue_count":        risk_result["medium_count"],
            "overclaim_count":           overclaim_result["overclaim_count"],
            "repetition_issue_count":    repetition_result.get("issue_count", 0),
            "patches_applied":           verified_script.get("patches_applied_count", 0),
        },
        "handoff": {
            "ready_for_layer_10": rec in ("approved", "approved_with_warnings"),
            "next_layer":         "layer_10_memory_learning",
        },
    }
    _write_json(layer9_dir / "layer9_manifest.json", manifest)
    return manifest
