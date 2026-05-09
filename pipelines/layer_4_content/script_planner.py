"""
Script Planner — Layer 4, Module 1

Reads the context packet from Layer 3 and produces a structured video plan:
  - Video angle (the "why should I watch this" framing)
  - Tone (analytical, excited, sceptical, etc.)
  - Throughline (the single idea the viewer walks away with)
  - Sections with timestamps, duration, direction, and which claims to use

The planner thinks about STRUCTURE only — no actual script writing.
This separation matters: a planner that focuses on narrative arc produces
a better structure than a writer trying to plan and write simultaneously.

The plan output is what drives the script writer in Module 2.
Every section in the plan maps directly to a written segment in the script.

Output: plan_{date}.json — consumed by script_writer.py next.

Usage:
    python script_planner.py                    # uses latest context packet
    python script_planner.py --input output/.../context_packet_2026-05-09.json
    python script_planner.py --duration 10      # target video length in minutes (default: 10)
"""

import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.paths import INTEL_CONTEXT, CONTENT_SCRIPTS, ensure_output_dirs
from config.llm_config import get_profile
from llm.llm_client import make_llm
from llm.llm_logger import call_llm


MODULE_NAME = "script_planner"


def build_claims_digest(packet):
    """
    Build a compact digest of available facts for the planner.
    The planner will assign specific claims to specific sections.
    """
    stats    = packet.get("key_statistics", [])
    facts    = packet.get("key_facts", [])[:8]   # top 8 product facts

    lines = ["STATISTICS (use these on-screen — exact wording):"]
    for s in stats:
        lines.append(f"  STAT: {s['claim']}")

    lines.append("")
    lines.append("KEY PRODUCT FACTS:")
    for f in facts:
        lines.append(f"  FACT: {f['claim']}")

    return "\n".join(lines)


def build_prompt(packet, target_duration_minutes):
    """
    Build the planning prompt. The LLM is a video producer, not a writer.
    It designs the structure — section order, angle, timing, what to emphasize.
    """
    topic      = packet.get("topic", "")
    headline   = packet.get("headline", "")
    summary    = packet.get("summary", "")[:800]      # first 800 chars for context
    background = packet.get("background", "")[:400]
    why_matters = packet.get("why_it_matters", "")[:400]
    tech       = packet.get("technical_breakdown", "")[:400]
    comparisons = packet.get("comparisons", "")[:400]
    audience   = packet.get("audience_angle", "")
    claims_block = build_claims_digest(packet)

    target_words = target_duration_minutes * 130   # ~130 words/minute speaking pace

    prompt = f"""You are an experienced YouTube video producer for an AI news channel with 500K subscribers. Your audience: developers, AI researchers, tech professionals — smart people who want depth, not hype.

You have been given a research packet on today's top story. Your job is to design the VIDEO STRUCTURE — NOT to write the script. Just the plan.

---
TOPIC: {topic}
SUGGESTED HEADLINE: {headline}

STORY SUMMARY:
{summary}...

BACKGROUND:
{background}...

WHY IT MATTERS:
{why_matters}...

TECHNICAL BREAKDOWN:
{tech}...

COMPETITIVE COMPARISONS:
{comparisons}...

AUDIENCE ANGLE (for the outro):
{audience}

AVAILABLE FACTS:
{claims_block}
---

Design a {target_duration_minutes}-minute video plan (target: ~{target_words} spoken words).

First, decide three things:
1. ANGLE: What is this video's unique take? Not just "here's what happened" — what LENS does the viewer watch this through? (e.g. "Anthropic quietly raised the bar for production AI agents")
2. TONE: One of: [explanatory, analytical, enthusiastic, sceptical, investigative]
3. THROUGHLINE: The ONE sentence a viewer should remember 24 hours after watching.

Then design the sections. A good {target_duration_minutes}-min AI video has:
  - Hook (0:00–0:30): A surprising stat or question that makes viewers stay
  - Intro (0:30–1:00): What this video covers
  - 3–5 content sections (the bulk, each 90–150 seconds)
  - Outro (last 60–90 sec): Takeaway + what viewer should do next

For each section output EXACTLY this format (one section per block):

SECTION: [section_id]
TITLE: [section display title]
TIMESTAMP: [MM:SS]
DURATION_SECONDS: [number]
DIRECTION: [2-4 sentences telling the writer exactly what to say and how to say it in this section — be specific about facts to include, emotional beat, and how it connects to the next section]
CLAIMS_TO_USE: [comma-separated list of which STAT or FACT labels to include, or "none"]

After all sections, add:
ANGLE: [your video angle]
TONE: [tone word]
THROUGHLINE: [one memorable sentence]"""

    return prompt


def parse_plan_response(response_text, topic, target_duration):
    """
    Parse the LLM's structured plan response into a clean dict.
    The LLM is instructed to use exact labels — we scan for those.
    """
    sections = []
    current_section = {}

    # Also grab the three summary lines at the end
    angle = ""
    tone = ""
    throughline = ""

    for line in response_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            # Blank line = end of a section block
            if current_section.get("id"):
                sections.append(current_section)
                current_section = {}
            continue

        if stripped.startswith("SECTION:"):
            # New section starting — save any existing
            if current_section.get("id"):
                sections.append(current_section)
            current_section = {"id": stripped.split(":", 1)[1].strip()}

        elif stripped.startswith("TITLE:"):
            current_section["title"] = stripped.split(":", 1)[1].strip()

        elif stripped.startswith("TIMESTAMP:"):
            current_section["timestamp"] = stripped.split(":", 1)[1].strip()

        elif stripped.startswith("DURATION_SECONDS:"):
            val = stripped.split(":", 1)[1].strip()
            current_section["duration_seconds"] = int(val) if val.isdigit() else 90

        elif stripped.startswith("DIRECTION:"):
            current_section["direction"] = stripped.split(":", 1)[1].strip()

        elif stripped.startswith("CLAIMS_TO_USE:"):
            raw = stripped.split(":", 1)[1].strip()
            current_section["claims_to_use"] = [c.strip() for c in raw.split(",") if c.strip() and c.strip().lower() != "none"]

        elif stripped.startswith("ANGLE:"):
            angle = stripped.split(":", 1)[1].strip()

        elif stripped.startswith("TONE:"):
            tone = stripped.split(":", 1)[1].strip()

        elif stripped.startswith("THROUGHLINE:"):
            throughline = stripped.split(":", 1)[1].strip()

    # Catch last section if no trailing blank line
    if current_section.get("id"):
        sections.append(current_section)

    total_seconds = sum(s.get("duration_seconds", 90) for s in sections)

    return {
        "topic":                    topic,
        "generated_at":             datetime.now().isoformat(),
        "target_duration_minutes":  target_duration,
        "estimated_duration_seconds": total_seconds,
        "estimated_duration_minutes": round(total_seconds / 60, 1),
        "angle":                    angle,
        "tone":                     tone,
        "throughline":              throughline,
        "section_count":            len(sections),
        "sections":                 sections,
    }


def run_planner(packet_path, target_duration=10):
    """Load context packet, build plan, return plan dict."""
    packet = json.loads(Path(packet_path).read_text(encoding="utf-8"))
    topic  = packet.get("topic", "")

    print(f"  Topic:    {topic}")
    print(f"  Score:    {packet.get('story_score', 0)}/100")
    print(f"  Target:   {target_duration} min (~{target_duration * 130} words)")

    prompt = build_prompt(packet, target_duration)
    print(f"\n  Prompt built — {len(prompt):,} chars (~{len(prompt)//4:,} tokens)")

    profile = get_profile(MODULE_NAME)
    llm = make_llm(**profile)

    response_text = call_llm(
        llm,
        prompt,
        module=MODULE_NAME,
        metadata={
            "topic": topic,
            "target_duration_minutes": target_duration,
        }
    )

    plan = parse_plan_response(response_text, topic, target_duration)
    return plan


def save_plan(plan, date_str=None):
    """Save plan to output/layer_4_content/scripts/"""
    ensure_output_dirs()

    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    filepath = CONTENT_SCRIPTS / f"plan_{date_str}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)

    return filepath


def find_latest(directory, pattern):
    candidates = sorted(Path(directory).glob(pattern), reverse=True)
    return candidates[0] if candidates else None


# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plan the video structure from the context packet")
    parser.add_argument("--input",    help="Path to context_packet JSON")
    parser.add_argument("--duration", type=int, default=10, help="Target video duration in minutes (default: 10)")
    args = parser.parse_args()

    packet_path = args.input or find_latest(INTEL_CONTEXT, "context_packet_*.json")
    if not packet_path:
        print("No context packet found. Run Layer 3 first.")
        sys.exit(1)

    date_str = Path(packet_path).stem.replace("context_packet_", "")

    print(f"Context packet: {packet_path}")
    print()

    profile = get_profile(MODULE_NAME)
    print(f"LLM profile: {profile['provider']}/{profile['model']}")
    print()

    plan = run_planner(packet_path, target_duration=args.duration)

    filepath = save_plan(plan, date_str)

    # Print the plan
    print()
    print(f"{'='*65}")
    print(f"  VIDEO PLAN")
    print(f"{'='*65}")
    print(f"  Angle:      {plan['angle']}")
    print(f"  Tone:       {plan['tone']}")
    print(f"  Throughline: {plan['throughline']}")
    print(f"  Est. duration: {plan['estimated_duration_minutes']} min ({plan['estimated_duration_seconds']}s)")
    print()
    print(f"  {'#':<4} {'Title':<30} {'Time':<8} {'Dur(s)':<8} {'Claims'}")
    print(f"  {'-'*70}")
    for i, s in enumerate(plan["sections"], 1):
        claims = ", ".join(s.get("claims_to_use", []))[:25] or "—"
        title = s.get("title", s.get("id", ""))[:28]
        ts = s.get("timestamp", "")
        dur = s.get("duration_seconds", 0)
        print(f"  {i:<4} {title:<30} {ts:<8} {dur:<8} {claims}")
    print()
    for i, s in enumerate(plan["sections"], 1):
        print(f"  Section {i}: {s.get('title', s.get('id', ''))}")
        print(f"    Direction: {s.get('direction', '')[:120]}...")
        print()

    print(f"Saved to: {filepath}")
    print(f"\nNext: python pipelines/layer_4_content/script_writer.py")
