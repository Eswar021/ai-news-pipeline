"""
Module: output_contract_builder
Layer: 0 — Channel Strategy + Run Control
Purpose: Declare the active pipeline's expected output file paths for every layer.
         This contract is intentionally aligned to the current run-scoped folder layout
         under data/runs/{run_id}/layer_X/.
"""

from pathlib import Path


def build_output_contract(
    run_id: str,
    eligible_formats: list,
    data_dir: Path,
    scripts_dir: Path,
) -> dict:
    """
    Builds the output contract for this run: where every layer writes its core outputs.

    Path structure:
      data/runs/{run_id}/  — run-scoped pipeline data and layer outputs
      data/runs/{run_id}/layer_9/  — current reviewer-facing final package location

    Returns:
        dict with: output_contract (run_data_dir, run_scripts_dir, required_layer_outputs,
        final_package)
    """
    run_data_dir = data_dir / "runs" / run_id
    # The active pipeline keeps final review assets inside layer_9. We retain the
    # run_scripts_dir field for compatibility with existing manifest consumers.
    run_scripts_dir = run_data_dir / "layer_9"

    required_layer_outputs = {
        "layer_0_manifest":            str(run_data_dir / "run_manifest.json"),
        "layer_0_validation_report":   str(run_data_dir / "layer0_validation_report.json"),
        "layer_0_config_snapshot":     str(run_data_dir / "run_config_snapshot.json"),

        "layer_1_raw_documents":       str(run_data_dir / "layer_1" / "raw_documents.jsonl"),
        "layer_1_extraction_manifest": str(run_data_dir / "layer_1" / "extraction_manifest.json"),
        "layer_1_validation_report":   str(run_data_dir / "layer_1" / "layer1_validation_report.json"),

        "layer_2_canonical_documents": str(run_data_dir / "layer_2" / "canonical_documents.jsonl"),
        "layer_2_source_spans":        str(run_data_dir / "layer_2" / "source_spans.jsonl"),
        "layer_2_provenance_map":      str(run_data_dir / "layer_2" / "provenance_map.jsonl"),
        "layer_2_manifest":            str(run_data_dir / "layer_2" / "layer2_manifest.json"),
        "layer_2_validation_report":   str(run_data_dir / "layer_2" / "layer2_validation_report.json"),

        "layer_3_story_clusters":      str(run_data_dir / "layer_3" / "story_clusters.json"),
        "layer_3_ranked_stories":      str(run_data_dir / "layer_3" / "ranked_stories.json"),
        "layer_3_story_timeline":      str(run_data_dir / "layer_3" / "story_timeline.json"),
        "layer_3_manifest":            str(run_data_dir / "layer_3" / "layer3_manifest.json"),
        "layer_3_validation_report":   str(run_data_dir / "layer_3" / "layer3_validation_report.json"),

        "layer_4_verified_claims":     str(run_data_dir / "layer_4" / "verified_claims.jsonl"),
        "layer_4_rejected_claims":     str(run_data_dir / "layer_4" / "rejected_claims.jsonl"),
        "layer_4_story_fact_sheets":   str(run_data_dir / "layer_4" / "story_fact_sheets.json"),
        "layer_4_evidence_density_report": str(run_data_dir / "layer_4" / "evidence_density_report.json"),
        "layer_4_evidence_gaps":       str(run_data_dir / "layer_4" / "evidence_gaps.json"),
        "layer_4_contradictions":      str(run_data_dir / "layer_4" / "contradictions.json"),
        "layer_4_manifest":            str(run_data_dir / "layer_4" / "layer4_manifest.json"),
        "layer_4_validation_report":   str(run_data_dir / "layer_4" / "layer4_validation_report.json"),

        "layer_5_editorial_candidates": str(run_data_dir / "layer_5" / "editorial_candidates.json"),
        "layer_5_story_editorial_assessments": str(run_data_dir / "layer_5" / "story_editorial_assessments.json"),
        "layer_5_editorial_decision":   str(run_data_dir / "layer_5" / "editorial_decision.json"),
        "layer_5_selected_video_brief": str(run_data_dir / "layer_5" / "selected_video_brief.json"),
        "layer_5_manifest":             str(run_data_dir / "layer_5" / "layer5_manifest.json"),
        "layer_5_validation_report":    str(run_data_dir / "layer_5" / "layer5_validation_report.json"),

        "layer_6_research_packet":     str(run_data_dir / "layer_6" / "research_packet.json"),
        "layer_6_source_pack":         str(run_data_dir / "layer_6" / "source_pack.json"),
        "layer_6_packet_context":      str(run_data_dir / "layer_6" / "packet_context_for_layer7.json"),
        "layer_6_manifest":            str(run_data_dir / "layer_6" / "layer6_manifest.json"),
        "layer_6_validation_report":   str(run_data_dir / "layer_6" / "layer6_validation_report.json"),

        "layer_7_video_plan":          str(run_data_dir / "layer_7" / "video_plan.json"),
        "layer_7_script_writer_brief": str(run_data_dir / "layer_7" / "script_writer_brief.json"),
        "layer_7_title_thumbnail_plan": str(run_data_dir / "layer_7" / "title_thumbnail_plan.json"),
        "layer_7_manifest":            str(run_data_dir / "layer_7" / "layer7_manifest.json"),
        "layer_7_validation_report":   str(run_data_dir / "layer_7" / "layer7_validation_report.json"),

        "layer_8_script_md":           str(run_data_dir / "layer_8" / "script.md"),
        "layer_8_generated_script":    str(run_data_dir / "layer_8" / "generated_script.json"),
        "layer_8_sentence_claim_map":  str(run_data_dir / "layer_8" / "sentence_claim_map.jsonl"),
        "layer_8_sentence_source_map": str(run_data_dir / "layer_8" / "sentence_source_map.jsonl"),
        "layer_8_youtube_metadata":    str(run_data_dir / "layer_8" / "youtube_metadata.json"),
        "layer_8_manifest":            str(run_data_dir / "layer_8" / "layer8_manifest.json"),
        "layer_8_validation_report":   str(run_data_dir / "layer_8" / "layer8_validation_report.json"),

        "layer_9_verification_report": str(run_scripts_dir / "verification_report.json"),
        "layer_9_revision_package":    str(run_scripts_dir / "revision_package.json"),
        "layer_9_verified_script":     str(run_scripts_dir / "verified_script.md"),
        "layer_9_verified_youtube_metadata": str(run_scripts_dir / "verified_youtube_metadata.json"),
        "layer_9_final_publish_package": str(run_scripts_dir / "final_publish_package.json"),
        "layer_9_manifest":            str(run_scripts_dir / "layer9_manifest.json"),
        "layer_9_validation_report":   str(run_scripts_dir / "layer9_validation_report.json"),

        "layer_10_manifest":           str(run_data_dir / "layer_10" / "layer10_manifest.json"),
        "layer_10_validation_report":  str(run_data_dir / "layer_10" / "layer10_validation_report.json"),
        "layer_10_video_memory":       str(data_dir / "memory" / "video_memory.jsonl"),
        "layer_10_claim_ledger":       str(data_dir / "memory" / "claim_ledger.jsonl"),
        "layer_10_memory_index":       str(data_dir / "memory" / "memory_index.json"),
        "layer_10_memory_snapshot":    str(data_dir / "memory" / "memory_snapshot.json"),
    }

    # The final package is what a human reviewer receives at the end of a successful run
    final_package = [
        "verified_script.md",
        "verified_youtube_metadata.json",
        "verification_report.json",
        "revision_package.json",
        "final_publish_package.json",
    ]

    return {
        "output_contract": {
            "run_data_dir": str(run_data_dir),
            "run_scripts_dir": str(run_scripts_dir),
            "required_layer_outputs": required_layer_outputs,
            "final_package": final_package,
        }
    }
