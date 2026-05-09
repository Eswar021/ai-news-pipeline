"""
Script Writer — Layer 4, Module 2

Takes the video plan (structure) + context packet (all research) and writes
the full word-for-word YouTube script.

Strategy: write ALL sections in a single LLM call, not section-by-section.
  - The plan already gives detailed direction per section
  - A single call lets the LLM maintain narrative voice and flow throughout
  - Avoids repetition or tone shifts between separate calls
  - ~1,300 words output is well within any model's output window

Writing rules enforced in the prompt:
  1. Write for speaking — short sentences, active voice, no passive constructions
  2. Every number needs context — explain what it means, don't just cite it
  3. Exact claim wording for statistics — zero paraphrasing of numbers
  4. Screen directions in [SHOW: ...] blocks — placed where relevant
  5. Each section ends with a one-sentence bridge to the next
  6. No filler phrases ("In conclusion...", "As we can see...")
  7. No hype words (revolutionary, game-changing, groundbreaking)

Output: script_{date}.txt (raw) + script_{date}.md (formatted with headers)
Consumed by output_packager.py next.

Usage:
    python script_writer.py                     # uses latest plan + context packet
    python script_writer.py --plan output/.../plan_2026-05-09.json
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


MODULE_NAME = "script_writer"


def build_sections_block(plan):
    """
    Convert the plan sections into a clear, directive block for the writer prompt.
    Each section gets its own numbered block with timing, direction, and claims.
    """
    lines = []
    for i, s in enumerate(plan["sections"], 1):
        title    = s.get("title", s.get("id", f"Section {i}"))
        ts       = s.get("timestamp", "")
        dur      = s.get("duration_seconds", 90)
        words    = round(dur / 60 * 130)
        direction = s.get("direction", "")
        claims   = s.get("claims_to_use", [])

        lines.append(f"SECTION {i}: {title}")
        lines.append(f"Timestamp: {ts} | Duration: {dur}s | Target words: ~{words}")
        lines.append(f"Direction: {direction}")
        if claims:
            lines.append(f"Facts to include: {'; '.join(claims[:4])}")
        lines.append("")

    return "\n".join(lines)


def build_facts_reference(packet):
    """
    Build a compact reference of ALL verified facts the writer can use.
    Grouped by type so the writer can quickly find what they need.
    """
    stats  = packet.get("key_statistics", [])
    facts  = packet.get("key_facts", [])

    lines = ["=== VERIFIED FACTS REFERENCE (use EXACT wording for statistics) ===", ""]
    lines.append("STATISTICS — use these verbatim when citing numbers:")
    for s in stats:
        lines.append(f"  • {s['claim']}  [source: {s['source_name']}]")

    lines.append("")
    lines.append("KEY PRODUCT FACTS:")
    for f in facts[:12]:
        lines.append(f"  • {f['claim']}")

    return "\n".join(lines)


def build_prompt(plan, packet):
    """
    Build the full script writing prompt.
    The writer receives: plan (structure) + facts reference (what to say) +
    style rules (how to say it).
    """
    topic       = plan.get("topic", "")
    angle       = plan.get("angle", "")
    tone        = plan.get("tone", "analytical")
    throughline = plan.get("throughline", "")
    total_words = plan.get("target_duration_minutes", 10) * 130
    sections_block = build_sections_block(plan)
    facts_block    = build_facts_reference(packet)

    prompt = f"""You are a professional YouTube scriptwriter for an AI news channel with 500K subscribers. Your audience: developers, AI researchers, and tech professionals — people who want depth and accuracy, not hype.

Write a complete, word-for-word YouTube video script. This is the exact text the host will read on camera.

---
TOPIC: {topic}
VIDEO ANGLE: {angle}
TONE: {tone}
THROUGHLINE (the idea viewers remember): {throughline}
TARGET LENGTH: ~{total_words} words total
---

{facts_block}

---
VIDEO STRUCTURE TO FOLLOW:
{sections_block}
---

WRITING RULES — follow these strictly:

1. WRITE FOR SPEAKING, NOT READING
   - Short sentences. Vary sentence length for rhythm.
   - Active voice always. No passive constructions.
   - Contractions are fine ("it's", "we're", "that's")
   - Write how a smart person actually talks, not how they write

2. NUMBERS NEED CONTEXT
   - Never cite a number without explaining what it means
   - Bad: "scored 0.715"
   - Good: "scored 0.715 out of 1.0 — that's the top mark across all six evaluation categories"

3. EXACT WORDING FOR STATISTICS
   - When citing a benchmark number or percentage, use the EXACT claim wording from the facts reference
   - Do not round, paraphrase, or restate statistics in your own words

4. SCREEN DIRECTIONS
   - Add [SHOW: description] for any visual the editor should display
   - Keep it brief: [SHOW: coding benchmark chart], [SHOW: Anthropic pricing page]
   - Place screen directions on their own line, right where the stat is mentioned

5. SECTION BRIDGES
   - End every section (except the outro) with one sentence that flows into the next section
   - Make it feel natural, not like a chapter marker

6. FORBIDDEN PHRASES
   - Do not use: "game-changing", "revolutionary", "groundbreaking", "in conclusion",
     "as we can see", "it's worth noting", "at the end of the day", "game changer"
   - No filler. Every sentence earns its place.

7. FORMAT
   - Start each section with: [SECTION: Title | Timestamp]
   - This is the only formatting — no markdown headers, no bullet points in the script itself
   - The script should read as one continuous spoken piece divided by section markers

Write the complete script now:"""

    return prompt


def parse_script(response_text, plan):
    """
    Split the raw script into individual sections by their markers.
    Returns both the full raw text and a list of section dicts.
    """
    sections_output = []
    current_section_text = []
    current_header = None

    for line in response_text.split("\n"):
        stripped = line.strip()

        # Detect section markers: [SECTION: Title | Timestamp]
        if stripped.startswith("[SECTION:") and "|" in stripped:
            # Save previous section
            if current_header is not None:
                sections_output.append({
                    "header": current_header,
                    "text": "\n".join(current_section_text).strip(),
                })
            current_header = stripped
            current_section_text = []
        else:
            current_section_text.append(line)

    # Save last section
    if current_header is not None:
        sections_output.append({
            "header": current_header,
            "text": "\n".join(current_section_text).strip(),
        })

    # If parsing found no markers (LLM didn't follow format), treat as single block
    if not sections_output:
        sections_output = [{"header": "[SCRIPT]", "text": response_text.strip()}]

    return sections_output


def count_words(text):
    return len(text.split())


def run_writer(plan_path, packet_path):
    """Load plan + context packet, run LLM writer, return script data."""
    plan   = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    packet = json.loads(Path(packet_path).read_text(encoding="utf-8"))

    topic = plan.get("topic", "")
    target_words = plan.get("target_duration_minutes", 10) * 130

    print(f"  Topic:    {topic}")
    print(f"  Sections: {plan['section_count']}")
    print(f"  Target:   ~{target_words} words ({plan['target_duration_minutes']} min)")

    prompt = build_prompt(plan, packet)
    print(f"\n  Prompt built — {len(prompt):,} chars (~{len(prompt)//4:,} tokens)")

    profile = get_profile(MODULE_NAME)
    llm = make_llm(**profile)

    raw_script = call_llm(
        llm,
        prompt,
        module=MODULE_NAME,
        metadata={
            "topic": topic,
            "target_words": target_words,
            "section_count": plan["section_count"],
        }
    )

    # Parse sections
    sections = parse_script(raw_script, plan)
    total_words = count_words(raw_script)
    est_duration = round(total_words / 130, 1)

    return {
        "topic":           topic,
        "generated_at":    datetime.now().isoformat(),
        "llm_profile":     profile,
        "angle":           plan.get("angle", ""),
        "tone":            plan.get("tone", ""),
        "throughline":     plan.get("throughline", ""),
        "total_words":     total_words,
        "est_duration_min": est_duration,
        "section_count":   len(sections),
        "sections":        sections,
        "raw_script":      raw_script,
    }


def save_script(script_data, date_str=None):
    """
    Save two versions of the script:
      - script_{date}.txt  — plain text, ready for teleprompter
      - script_{date}.md   — formatted with section callouts
    """
    ensure_output_dirs()

    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    # ── Plain text version ──
    txt_path = CONTENT_SCRIPTS / f"script_{date_str}.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"TOPIC: {script_data['topic']}\n")
        f.write(f"DATE: {date_str}\n")
        f.write(f"WORDS: {script_data['total_words']} (~{script_data['est_duration_min']} min)\n")
        f.write(f"ANGLE: {script_data['angle']}\n")
        f.write(f"THROUGHLINE: {script_data['throughline']}\n")
        f.write("\n" + "="*65 + "\n\n")
        f.write(script_data["raw_script"])

    # ── Markdown version ──
    md_path = CONTENT_SCRIPTS / f"script_{date_str}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# {script_data['topic']}\n\n")
        f.write(f"**Date:** {date_str}  \n")
        f.write(f"**Words:** {script_data['total_words']} (~{script_data['est_duration_min']} min)  \n")
        f.write(f"**Angle:** {script_data['angle']}  \n")
        f.write(f"**Throughline:** *{script_data['throughline']}*  \n\n")
        f.write("---\n\n")

        for s in script_data["sections"]:
            header = s["header"].strip("[]")
            f.write(f"## {header}\n\n")
            # Bold any [SHOW: ...] directions
            text = s["text"]
            f.write(text + "\n\n")
            f.write("---\n\n")

    return txt_path, md_path


def find_latest(directory, pattern):
    candidates = sorted(Path(directory).glob(pattern), reverse=True)
    return candidates[0] if candidates else None


# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Write the full YouTube script from the video plan")
    parser.add_argument("--plan",   help="Path to plan JSON")
    parser.add_argument("--packet", help="Path to context_packet JSON")
    args = parser.parse_args()

    plan_path   = args.plan   or find_latest(CONTENT_SCRIPTS, "plan_*.json")
    packet_path = args.packet or find_latest(INTEL_CONTEXT,   "context_packet_*.json")

    if not plan_path:
        print("No plan found. Run script_planner.py first."); sys.exit(1)
    if not packet_path:
        print("No context packet found. Run Layer 3 first."); sys.exit(1)

    date_str = Path(plan_path).stem.replace("plan_", "")

    print(f"Plan:    {plan_path}")
    print(f"Packet:  {packet_path}")
    print()

    profile = get_profile(MODULE_NAME)
    print(f"LLM profile: {profile['provider']}/{profile['model']}")
    print()

    script_data = run_writer(plan_path, packet_path)

    txt_path, md_path = save_script(script_data, date_str)

    # Print summary + preview
    print()
    print(f"{'='*65}")
    print(f"  SCRIPT WRITTEN")
    print(f"{'='*65}")
    print(f"  Words:    {script_data['total_words']} (~{script_data['est_duration_min']} min)")
    print(f"  Sections: {script_data['section_count']}")
    print()
    for s in script_data["sections"]:
        words = count_words(s["text"])
        print(f"  {s['header'][:55]}")
        print(f"    {words} words | preview: {s['text'][:80].strip()}...")
        print()
    print(f"  Saved:")
    print(f"    TXT: {txt_path}")
    print(f"    MD:  {md_path}")
    print()
    print(f"\n{'='*65}")
    print("  SCRIPT PREVIEW (first 600 chars)")
    print(f"{'='*65}")
    print(script_data["raw_script"][:600])
    print("...")
    print(f"\nNext: python pipelines/layer_4_content/output_packager.py")
