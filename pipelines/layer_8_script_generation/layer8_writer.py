"""
Layer 8 — Module 10: Layer 8 Output Writer

Writes all Layer 8 output files and returns the layer8_manifest dict.

Output files:
  script.md                   — full script in markdown with section headers
  script.txt                  — plain text (read-aloud ready)
  generated_script.json       — script metadata + full_text + word counts
  section_scripts.json        — per-section scripts with claim tracking
  sentence_claim_map.jsonl    — sentence → claim_ids map
  sentence_source_map.jsonl   — sentence → source_urls map
  claim_usage_report.json     — used vs unused safe claims
  cautious_language_report.json — blocked phrase + cautious language check
  shorts_clips_suggestions.json — clip moment suggestions
  youtube_metadata.json       — chapters + description + tags + source list
  script_generation_report.json — summary stats
  layer8_manifest.json        — manifest

Key function:
    write(...) → manifest dict
"""

import json
from datetime import datetime, timezone
from config.time_utils import now_project_iso
from pathlib import Path


def _write_json(path: Path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _write_jsonl(path: Path, records: list):
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def _build_script_md(section_scripts: list, layer8_ctx: dict) -> str:
    title_rec  = layer8_ctx.get("title_recommendation", {})
    top_title  = title_rec.get("top_title", "AI Signal Brief")
    vi         = layer8_ctx.get("video_identity", {})
    fmt        = vi.get("selected_format", "roundup")

    lines = [f"# {top_title}", f"*Format: {fmt}*", ""]

    for sec in section_scripts:
        label = sec["section_key"].replace("_", " ").title()
        lines.append(f"## {label}")
        lines.append("")
        lines.append(sec.get("narration_text", ""))
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def write(
    run_id:                  str,
    layer8_dir:              Path,
    layer7_dir:              Path,
    layer8_ctx:              dict,
    section_scripts:         list,
    sentence_maps:           dict,
    claim_usage_report:      dict,
    cautious_language_report: dict,
    shorts_suggestions:      list,
    youtube_metadata:        dict,
) -> dict:
    layer8_dir.mkdir(parents=True, exist_ok=True)
    now = now_project_iso()

    total_words = sum(s.get("word_count", 0) for s in section_scripts)
    total_secs  = sum(s.get("estimated_seconds", 0) for s in section_scripts)
    full_text   = "\n\n".join(s.get("narration_text", "") for s in section_scripts)

    # ── script.md ────────────────────────────────────────────────────────────
    script_md = _build_script_md(section_scripts, layer8_ctx)
    (layer8_dir / "script.md").write_text(script_md, encoding="utf-8")

    # ── script.txt ────────────────────────────────────────────────────────────
    (layer8_dir / "script.txt").write_text(full_text, encoding="utf-8")

    # ── generated_script.json ────────────────────────────────────────────────
    _write_json(layer8_dir / "generated_script.json", {
        "run_id":              run_id,
        "generated_at":        now,
        "brief_id":            layer8_ctx.get("brief_id", ""),
        "selected_format":     layer8_ctx["video_identity"].get("selected_format", ""),
        "full_script_text":    full_text,
        "total_word_count":    total_words,
        "estimated_seconds":   total_secs,
        "estimated_minutes":   round(total_secs / 60, 1),
        "section_count":       len(section_scripts),
        "top_title":           layer8_ctx["title_recommendation"].get("top_title", ""),
    })

    # ── section_scripts.json ─────────────────────────────────────────────────
    _write_json(layer8_dir / "section_scripts.json", {
        "run_id":       run_id,
        "generated_at": now,
        "section_count": len(section_scripts),
        "sections":     section_scripts,
    })

    # ── sentence_claim_map.jsonl ──────────────────────────────────────────────
    _write_jsonl(layer8_dir / "sentence_claim_map.jsonl",
                 sentence_maps.get("sentence_claim_map", []))

    # ── sentence_source_map.jsonl ─────────────────────────────────────────────
    _write_jsonl(layer8_dir / "sentence_source_map.jsonl",
                 sentence_maps.get("sentence_source_map", []))

    # ── claim_usage_report.json ───────────────────────────────────────────────
    cur = dict(claim_usage_report)
    cur["run_id"]       = run_id
    cur["generated_at"] = now
    _write_json(layer8_dir / "claim_usage_report.json", cur)

    # ── cautious_language_report.json ─────────────────────────────────────────
    clr = dict(cautious_language_report)
    clr["run_id"]       = run_id
    clr["generated_at"] = now
    _write_json(layer8_dir / "cautious_language_report.json", clr)

    # ── shorts_clips_suggestions.json ─────────────────────────────────────────
    _write_json(layer8_dir / "shorts_clips_suggestions.json", {
        "run_id":            run_id,
        "generated_at":      now,
        "suggestion_count":  len(shorts_suggestions),
        "suggestions":       shorts_suggestions,
    })

    # ── youtube_metadata.json ─────────────────────────────────────────────────
    yt = dict(youtube_metadata)
    yt["run_id"]       = run_id
    yt["generated_at"] = now
    _write_json(layer8_dir / "youtube_metadata.json", yt)

    # ── script_generation_report.json ─────────────────────────────────────────
    _write_json(layer8_dir / "script_generation_report.json", {
        "run_id":              run_id,
        "generated_at":        now,
        "selected_format":     layer8_ctx["video_identity"].get("selected_format", ""),
        "total_word_count":    total_words,
        "estimated_seconds":   total_secs,
        "section_count":       len(section_scripts),
        "claim_usage_rate":    claim_usage_report.get("usage_rate", 0),
        "cautious_passed":     cautious_language_report.get("passed", False),
        "violation_count":     len(cautious_language_report.get("violations", [])),
        "shorts_count":        len(shorts_suggestions),
        "chapter_count":       youtube_metadata.get("chapter_count", 0),
        "source_count":        youtube_metadata.get("source_count", 0),
    })

    # ── layer8_manifest.json ──────────────────────────────────────────────────
    manifest = {
        "run_id":       run_id,
        "layer":        "layer_8_script_generation",
        "created_at":   now,
        "inputs": {
            "script_writer_brief": str(layer7_dir / "script_writer_brief.json"),
            "video_plan":          str(layer7_dir / "video_plan.json"),
        },
        "outputs": {
            "script_md":               str(layer8_dir / "script.md"),
            "script_txt":              str(layer8_dir / "script.txt"),
            "generated_script":        str(layer8_dir / "generated_script.json"),
            "section_scripts":         str(layer8_dir / "section_scripts.json"),
            "sentence_claim_map":      str(layer8_dir / "sentence_claim_map.jsonl"),
            "sentence_source_map":     str(layer8_dir / "sentence_source_map.jsonl"),
            "claim_usage_report":      str(layer8_dir / "claim_usage_report.json"),
            "cautious_language_report": str(layer8_dir / "cautious_language_report.json"),
            "shorts_clips_suggestions": str(layer8_dir / "shorts_clips_suggestions.json"),
            "youtube_metadata":        str(layer8_dir / "youtube_metadata.json"),
            "script_generation_report": str(layer8_dir / "script_generation_report.json"),
            "layer8_manifest":         str(layer8_dir / "layer8_manifest.json"),
        },
        "summary": {
            "selected_format":     layer8_ctx["video_identity"].get("selected_format", ""),
            "total_word_count":    total_words,
            "estimated_seconds":   total_secs,
            "section_count":       len(section_scripts),
            "claim_usage_rate":    claim_usage_report.get("usage_rate", 0),
            "cautious_passed":     cautious_language_report.get("passed", False),
            "shorts_count":        len(shorts_suggestions),
            "source_count":        youtube_metadata.get("source_count", 0),
        },
        "handoff": {
            "ready_for_layer_9": cautious_language_report.get("passed", False),
            "next_layer":        "layer_9_review_and_refinement",
            "script_path":       str(layer8_dir / "script.md"),
            "section_scripts_path": str(layer8_dir / "section_scripts.json"),
        },
    }
    _write_json(layer8_dir / "layer8_manifest.json", manifest)
    return manifest
