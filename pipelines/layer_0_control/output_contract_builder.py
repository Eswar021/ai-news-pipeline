"""
Module: output_contract_builder
Layer: 0 — Channel Strategy + Run Control
Purpose: Declare the full set of expected output file paths for every downstream layer.
         All layers write to paths defined here — no layer invents its own output path.
"""

from pathlib import Path


def build_output_contract(
    run_id: str,
    eligible_formats: list,
    data_dir: Path,
    scripts_dir: Path,
) -> dict:
    """
    Builds the output contract for this run: where every layer must write its outputs.

    Path structure:
      data/runs/{run_id}/  — all intermediate pipeline data (Layers 0-9 working files)
      output/scripts/{run_id}/  — final publishable outputs only (script, verification, etc.)

    Returns:
        dict with: output_contract (run_data_dir, run_scripts_dir, required_layer_outputs,
        final_package)
    """
    run_data_dir = data_dir / "runs" / run_id
    run_scripts_dir = scripts_dir / run_id

    required_layer_outputs = {
        "layer_0_manifest":            str(run_data_dir / "run_manifest.json"),
        "layer_0_validation_report":   str(run_data_dir / "layer0_validation_report.json"),
        "layer_0_config_snapshot":     str(run_data_dir / "run_config_snapshot.json"),

        "layer_1_raw_documents":       str(run_data_dir / "layer_1_raw_documents.jsonl"),
        "layer_1_manifest":            str(run_data_dir / "layer_1_manifest.json"),

        "layer_2_canonical_documents": str(run_data_dir / "layer_2_canonical_documents.jsonl"),
        "layer_2_source_spans":        str(run_data_dir / "layer_2_source_spans.jsonl"),
        "layer_2_provenance_map":      str(run_data_dir / "layer_2_provenance_map.jsonl"),
        "layer_2_manifest":            str(run_data_dir / "layer_2_manifest.json"),

        "layer_3_story_clusters":      str(run_data_dir / "layer_3_story_clusters.json"),
        "layer_3_ranked_stories":      str(run_data_dir / "layer_3_ranked_stories.json"),
        "layer_3_manifest":            str(run_data_dir / "layer_3_manifest.json"),

        "layer_4_atomic_claims":       str(run_data_dir / "layer_4_atomic_claims.jsonl"),
        "layer_4_story_fact_sheets":   str(run_data_dir / "layer_4_story_fact_sheets.json"),
        "layer_4_manifest":            str(run_data_dir / "layer_4_manifest.json"),

        "layer_5_editorial_decision":  str(run_data_dir / "layer_5_editorial_decision.json"),
        "layer_5_manifest":            str(run_data_dir / "layer_5_manifest.json"),

        "layer_6_research_packet":     str(run_data_dir / "layer_6_research_packet.json"),
        "layer_6_source_pack":         str(run_data_dir / "layer_6_source_pack.json"),
        "layer_6_manifest":            str(run_data_dir / "layer_6_manifest.json"),

        "layer_7_video_plan":          str(run_data_dir / "layer_7_video_plan.json"),
        "layer_7_script_writer_brief": str(run_data_dir / "layer_7_script_writer_brief.json"),
        "layer_7_manifest":            str(run_data_dir / "layer_7_manifest.json"),

        "layer_8_script":              str(run_scripts_dir / "script.md"),
        "layer_8_sentence_claim_map":  str(run_scripts_dir / "sentence_claim_map.jsonl"),
        "layer_8_sentence_source_map": str(run_scripts_dir / "sentence_source_map.jsonl"),
        "layer_8_manifest":            str(run_data_dir / "layer_8_manifest.json"),

        "layer_9_verified_script":     str(run_scripts_dir / "verified_script.md"),
        "layer_9_verification_report": str(run_scripts_dir / "verification_report.json"),
        "layer_9_manifest":            str(run_data_dir / "layer_9_manifest.json"),

        "layer_10_manifest":           str(run_scripts_dir / "layer10_manifest.json"),
    }

    # The final package is what a human reviewer receives at the end of a successful run
    final_package = [
        "verified_script.md",
        "youtube_description.md",
        "title_options.json",
        "thumbnail_angles.json",
        "source_pack.json",
        "sentence_source_map.jsonl",
        "sentence_claim_map.jsonl",
        "verification_report.json",
        "layer10_manifest.json",
    ]

    return {
        "output_contract": {
            "run_data_dir": str(run_data_dir),
            "run_scripts_dir": str(run_scripts_dir),
            "required_layer_outputs": required_layer_outputs,
            "final_package": final_package,
        }
    }
