"""
Output Packager — Layer 4, Module 3 (Final)

Pure code — no LLM. Reads the written script + context packet and
bundles everything into a clean, ready-to-use folder.

What it creates:
  output/layer_4_content/scripts/{date}_{slug}/
    ├── script.txt        ← plain text for teleprompter / recording
    ├── script.md         ← formatted with section headers for editing
    ├── sources.json      ← list of cited URLs for YouTube description box
    └── metadata.json     ← topic, word count, duration estimate, models used

The folder name uses a slug derived from the topic so you can tell
videos apart at a glance: 2026-05-09_claude_opus_4_7/

Usage:
    python output_packager.py                   # uses latest script + context packet
    python output_packager.py --date 2026-05-09
"""

import sys
import re
import json
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.paths import INTEL_CONTEXT, CONTENT_SCRIPTS, ensure_output_dirs


def slugify(text):
    """Convert a title into a filesystem-safe slug."""
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)      # remove special chars
    text = re.sub(r"[\s_]+", "_", text.strip()) # spaces → underscores
    text = re.sub(r"-+", "_", text)            # hyphens → underscores
    return text[:50]                            # cap at 50 chars


def clean_script_text(raw_script):
    """
    Clean the raw script for the plain-text teleprompter version.
    - Normalize the [SECTION:] headers to a clean visual separator
    - Remove any double blank lines
    - Keep [SHOW:] directions clearly visible but on their own line
    """
    lines = raw_script.split("\n")
    cleaned = []

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("[SECTION:"):
            # Add a clear visual separator before each section
            if cleaned:
                cleaned.append("")
                cleaned.append("─" * 65)
            cleaned.append(stripped)
            cleaned.append("")

        elif stripped.startswith("[SHOW:"):
            # Keep screen directions clearly indented
            cleaned.append(f"    {stripped}")

        else:
            cleaned.append(line)

    # Remove excessive blank lines (max 1 consecutive)
    result = []
    prev_blank = False
    for line in cleaned:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue
        result.append(line)
        prev_blank = is_blank

    return "\n".join(result)


def build_script_md(raw_script, script_data):
    """
    Build a formatted markdown version of the script.
    Section markers become H2 headers, [SHOW:] becomes callout blocks.
    """
    lines = []
    lines.append(f"# {script_data['topic']}")
    lines.append("")
    lines.append(f"**Date:** {script_data.get('date', '')}  ")
    lines.append(f"**Duration:** ~{script_data.get('est_duration_min', '?')} minutes ({script_data.get('total_words', '?')} words)  ")
    lines.append(f"**Angle:** {script_data.get('angle', '')}  ")
    lines.append(f"**Throughline:** *{script_data.get('throughline', '')}*")
    lines.append("")
    lines.append("---")
    lines.append("")

    for line in raw_script.split("\n"):
        stripped = line.strip()

        if stripped.startswith("[SECTION:"):
            # Extract section name from [SECTION: Title | Timestamp: 00:00]
            inner = stripped.strip("[]").replace("SECTION:", "").strip()
            lines.append(f"## {inner}")
            lines.append("")

        elif stripped.startswith("[SHOW:"):
            # Format as a visual callout
            inner = stripped.strip("[]").replace("SHOW:", "").strip()
            lines.append(f"> 📺 **On screen:** {inner}")
            lines.append("")

        elif stripped == "":
            lines.append("")

        else:
            lines.append(line)

    return "\n".join(lines)


def build_sources_list(packet):
    """
    Build the sources list for the YouTube description box.
    Only include sources with actual meaningful URLs (not github trending, pypi noise).
    """
    raw_sources = packet.get("sources", [])

    # Filter to useful sources for the description (Tier 1 and 1.5 always, Tier 2 if credible)
    sources_out = []
    for s in raw_sources:
        tier = s.get("trust_tier", 3)
        url  = s.get("url", "")
        title = s.get("title", "")
        publisher = s.get("publisher", "")

        # Skip noise: GitHub trending, PyPI, community-only sources
        if "github" in publisher.lower() and tier >= 3:
            continue
        if "pypi" in publisher.lower():
            continue

        sources_out.append({
            "title":     title,
            "url":       url,
            "publisher": publisher,
            "tier":      tier,
        })

    return sources_out


def build_metadata(script_data, packet, plan):
    """Build the metadata.json that documents this video's pipeline run."""
    return {
        "topic":          script_data["topic"],
        "date":           script_data.get("date", ""),
        "headline":       packet.get("headline", ""),
        "story_score":    packet.get("story_score", 0),
        "story_rank":     packet.get("story_rank", 0),

        "script": {
            "total_words":       script_data.get("total_words", 0),
            "est_duration_min":  script_data.get("est_duration_min", 0),
            "section_count":     script_data.get("section_count", 0),
        },

        "video_plan": {
            "angle":      plan.get("angle", ""),
            "tone":       plan.get("tone", ""),
            "throughline": plan.get("throughline", ""),
        },

        "pipeline": {
            "claims_extracted":   packet.get("pipeline_metadata", {}).get("total_claims", 0),
            "sources_used":       packet.get("source_count", 0),
            "enrichment_words":   packet.get("pipeline_metadata", {}).get("enrichment_words", 0),
            "llm_models": {
                **packet.get("pipeline_metadata", {}).get("llm_models_used", {}),
                "script_planner": plan.get("llm_profile", {}).get("model", ""),
                "script_writer":  script_data.get("llm_profile", {}).get("model", ""),
            }
        },

        "packaged_at": datetime.now().isoformat(),
    }


def run_packager(script_path, plan_path, packet_path):
    """
    Load all inputs, build the package folder with 4 files.
    Returns the folder path.
    """
    ensure_output_dirs()

    raw_script_txt = Path(script_path).read_text(encoding="utf-8")
    plan    = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    packet  = json.loads(Path(packet_path).read_text(encoding="utf-8"))

    # Parse the .txt file header lines to get metadata back
    lines = raw_script_txt.split("\n")
    meta_lines = {}
    script_start_idx = 0
    for i, line in enumerate(lines):
        if line.startswith("====="):
            script_start_idx = i + 2   # skip separator + blank
            break
        if ":" in line:
            key, _, val = line.partition(":")
            meta_lines[key.strip()] = val.strip()

    raw_script_body = "\n".join(lines[script_start_idx:])

    topic = meta_lines.get("TOPIC", packet.get("topic", ""))
    date_str = meta_lines.get("DATE", datetime.now().strftime("%Y-%m-%d"))
    total_words = int(meta_lines.get("WORDS", "0").split()[0]) if meta_lines.get("WORDS") else 0
    words_raw = meta_lines.get("WORDS", "")
    est_min = float(words_raw.split("(")[-1].replace("min)", "").replace("~", "").strip()) if "(" in words_raw else 0

    script_data = {
        "topic":           topic,
        "date":            date_str,
        "angle":           meta_lines.get("ANGLE", plan.get("angle", "")),
        "throughline":     meta_lines.get("THROUGHLINE", plan.get("throughline", "")),
        "total_words":     total_words,
        "est_duration_min": est_min,
        "section_count":   plan.get("section_count", 0),
        "llm_profile":     plan.get("llm_profile", {}),
    }

    # ── Create output folder ──
    slug = slugify(topic)
    folder_name = f"{date_str}_{slug}"
    folder = CONTENT_SCRIPTS / folder_name
    folder.mkdir(parents=True, exist_ok=True)

    # ── 1. script.txt — plain teleprompter version ──
    clean_txt = clean_script_text(raw_script_body)
    txt_header = (
        f"TOPIC: {topic}\n"
        f"DATE: {date_str}\n"
        f"WORDS: {total_words} (~{est_min} min)\n"
        f"ANGLE: {script_data['angle']}\n"
        f"THROUGHLINE: {script_data['throughline']}\n\n"
        + "=" * 65 + "\n\n"
    )
    (folder / "script.txt").write_text(txt_header + clean_txt, encoding="utf-8")

    # ── 2. script.md — formatted markdown version ──
    md_content = build_script_md(raw_script_body, script_data)
    (folder / "script.md").write_text(md_content, encoding="utf-8")

    # ── 3. sources.json — for YouTube description box ──
    sources = build_sources_list(packet)
    sources_out = {
        "topic": topic,
        "date":  date_str,
        "description_text": "\n".join(
            f"• {s['title']} — {s['url']}" for s in sources
        ),
        "sources": sources,
    }
    (folder / "sources.json").write_text(
        json.dumps(sources_out, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ── 4. metadata.json — pipeline audit trail ──
    metadata = build_metadata(script_data, packet, plan)
    (folder / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return folder, sources


def find_latest(directory, pattern):
    candidates = sorted(Path(directory).glob(pattern), reverse=True)
    return candidates[0] if candidates else None


# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Package the script into a ready-to-use folder")
    parser.add_argument("--date",   help="Date string to use (YYYY-MM-DD)")
    parser.add_argument("--script", help="Path to script .txt file")
    parser.add_argument("--plan",   help="Path to plan JSON")
    parser.add_argument("--packet", help="Path to context_packet JSON")
    args = parser.parse_args()

    # Resolve files
    if args.date:
        script_path = CONTENT_SCRIPTS / f"script_{args.date}.txt"
        plan_path   = CONTENT_SCRIPTS / f"plan_{args.date}.json"
        packet_path = find_latest(INTEL_CONTEXT, f"context_packet_{args.date}.json") or \
                      find_latest(INTEL_CONTEXT, "context_packet_*.json")
    else:
        script_path = args.script or find_latest(CONTENT_SCRIPTS, "script_*.txt")
        plan_path   = args.plan   or find_latest(CONTENT_SCRIPTS, "plan_*.json")
        packet_path = args.packet or find_latest(INTEL_CONTEXT,   "context_packet_*.json")

    if not script_path or not Path(script_path).exists():
        print("No script file found. Run script_writer.py first."); sys.exit(1)

    print(f"Script:  {script_path}")
    print(f"Plan:    {plan_path}")
    print(f"Packet:  {packet_path}")
    print()

    folder, sources = run_packager(script_path, plan_path, packet_path)

    # Print summary
    files = list(folder.iterdir())
    print(f"{'='*65}")
    print(f"  OUTPUT PACKAGE READY")
    print(f"{'='*65}")
    print(f"  Folder: {folder}")
    print()
    for f in sorted(files):
        size = f.stat().st_size
        print(f"  {f.name:<20} {size:>8,} bytes")

    print()
    print(f"  Sources for YouTube description ({len(sources)}):")
    for s in sources:
        print(f"    [Tier {s['tier']}] {s['publisher']:20} {s['title'][:40]}")
        print(f"            {s['url'][:65]}")

    print()
    print(f"  Description text (copy-paste ready):")
    print()
    desc = "\n".join(f"    • {s['title']} — {s['url']}" for s in sources)
    print(desc)

    print()
    print(f"{'='*65}")
    print(f"  Layer 4 complete. Open {folder}/script.txt and record.")
    print(f"{'='*65}")
