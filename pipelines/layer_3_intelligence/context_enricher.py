"""
Context Enricher — Layer 3, Module 4

Takes the summary + extracted claims and asks the LLM to add context that
is NOT in the source articles — background, implications, comparisons,
and the audience angle.

Key distinction vs previous modules:
  - Modules 2 & 3 (summarizer, claim_extractor) work STRICTLY from source articles.
    They only extract and reorganize what the sources say.
  - Module 4 (enricher) deliberately goes BEYOND the sources.
    It uses the LLM's training knowledge to add competitive context,
    industry history, and "why this matters" framing.

Five enrichment sections:
  1. background        — What happened before this? History, previous versions, competitive timeline
  2. why_it_matters    — Industry implications, who benefits, what changes
  3. technical_breakdown — Explain the key technical aspects for a general audience (no jargon)
  4. comparisons       — How does this compare to GPT-5, Gemini, Llama etc.
  5. audience_angle    — What should YOUR YouTube audience specifically care about

These five sections are kept SEPARATE in the output so the script writer
(Layer 4) can choose which sections to include and in what order.

Output: enriched_YYYY-MM-DD.json — consumed by context_builder.py next.

Usage:
    python context_enricher.py                                  # uses latest files
    python context_enricher.py --summary output/.../summary_2026-05-09.json
                               --claims  output/.../claims_2026-05-09.json
"""

import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.paths import INTEL_OUTPUT, INTEL_SUMMARIES, INTEL_RESEARCH, ensure_output_dirs
from config.llm_config import get_profile
from llm.llm_client import make_llm
from llm.llm_logger import call_llm


MODULE_NAME = "context_enricher"


def build_claims_digest(claims):
    """
    Build a compact summary of the key claims to include in the prompt.
    We don't need all 17 claims — just the statistics, comparisons,
    and key product facts give the LLM enough grounding.
    """
    priority_types = {"statistic", "comparison", "product_fact"}
    priority_claims = [c for c in claims if c.get("type") in priority_types]

    lines = []
    for c in priority_claims[:15]:   # cap at 15 to keep prompt tight
        lines.append(f"  - [{c['type']}] {c['claim']}")
    return "\n".join(lines)


def build_prompt(summary_data, claims_data, selected_topic_data):
    """
    Build the enrichment prompt. This is the most creative LLM call in the
    pipeline — the model draws on general training knowledge, not just sources.
    """
    topic = summary_data.get("topic", "")
    summary_text = summary_data.get("summary_text", "")
    entities = selected_topic_data.get("entities", {})
    companies = entities.get("companies", [])
    models = entities.get("models", [])
    claims_digest = build_claims_digest(claims_data.get("claims", []))

    prompt = f"""You are a senior AI industry analyst who writes content for a YouTube channel covering AI news for a technical-but-accessible audience (developers, AI enthusiasts, tech professionals).

You have just reviewed a news story and its verified facts. Now add the CONTEXT that makes this story meaningful — the background, implications, and angles that viewers need to understand why this matters.

---
TOPIC: {topic}

VERIFIED FACTS FROM SOURCES:
{claims_digest}

SUMMARY (for full context):
{summary_text[:1500]}...

COMPANIES MENTIONED: {', '.join(companies) if companies else 'None identified'}
MODELS MENTIONED: {', '.join(models) if models else 'None identified'}
---

Write FIVE separate sections. Be specific, not generic. Draw on your knowledge of the AI industry, competitive landscape, and technical context.

SECTION 1 — BACKGROUND
What is the relevant history here? Where did we come from to get to this announcement?
Include: previous model versions and their release dates, key milestones in this company's history, 
how this fits into the broader AI development timeline. Be specific about dates and version numbers you know.
(150-250 words)

SECTION 2 — WHY IT MATTERS
What are the real-world implications of this announcement?
Who benefits directly? What does this change for developers, enterprises, or end users?
What industry dynamics does this shift? Avoid vague statements — be concrete about impact.
(150-250 words)

SECTION 3 — TECHNICAL BREAKDOWN  
Explain the key technical aspects in plain language (no jargon, or jargon always explained).
What is actually happening under the hood that enables these improvements?
What architectural or training decisions likely drove these results?
This section should make a non-expert feel like they understand WHY the model is better.
(150-250 words)

SECTION 4 — COMPETITIVE COMPARISONS
How does this compare to the main competitors right now?
Compare specifically to: GPT-5, Gemini 2.5 Pro, Llama 4, and any other relevant models.
Use benchmark numbers you know from training where relevant. Be honest about where this model
leads and where competitors are stronger.
(150-250 words)

SECTION 5 — AUDIENCE ANGLE
What should our YouTube audience (developers, AI enthusiasts, tech professionals) specifically care about?
What is the most actionable takeaway? What should they try, watch out for, or think differently about
after hearing this story?
(100-150 words)

---

Output each section with its exact header label followed by the content. Example:
BACKGROUND
[content here]

WHY IT MATTERS
[content here]

TECHNICAL BREAKDOWN
[content here]

COMPETITIVE COMPARISONS
[content here]

AUDIENCE ANGLE
[content here]"""

    return prompt


def parse_enrichment_response(response_text):
    """
    Parse the LLM response into five named sections.
    The LLM is instructed to use exact section headers — we split on those.
    """
    sections = {
        "background": "",
        "why_it_matters": "",
        "technical_breakdown": "",
        "comparisons": "",
        "audience_angle": "",
    }

    # Map header labels to dict keys
    header_map = {
        "BACKGROUND": "background",
        "WHY IT MATTERS": "why_it_matters",
        "TECHNICAL BREAKDOWN": "technical_breakdown",
        "COMPETITIVE COMPARISONS": "comparisons",
        "AUDIENCE ANGLE": "audience_angle",
    }

    current_key = None
    current_lines = []

    for line in response_text.split("\n"):
        stripped = line.strip()

        # Check if this line is a section header
        matched_key = None
        for header, key in header_map.items():
            if stripped == header or stripped.startswith(header + ":"):
                matched_key = key
                break

        if matched_key:
            # Save the previous section
            if current_key and current_lines:
                sections[current_key] = "\n".join(current_lines).strip()
            current_key = matched_key
            current_lines = []
        elif current_key is not None:
            current_lines.append(line)

    # Save the last section
    if current_key and current_lines:
        sections[current_key] = "\n".join(current_lines).strip()

    return sections


def run_enricher(summary_path, claims_path, selected_topic_path):
    """
    Main enricher function. Returns the enriched context dict.
    """
    summary_data       = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    claims_data        = json.loads(Path(claims_path).read_text(encoding="utf-8"))
    selected_topic_data = json.loads(Path(selected_topic_path).read_text(encoding="utf-8"))

    topic = summary_data.get("topic", "")
    print(f"  Topic:   {topic}")
    print(f"  Claims:  {claims_data['total_claims']}")
    print(f"  Summary: {summary_data['word_count']} words")

    # Build prompt
    prompt = build_prompt(summary_data, claims_data, selected_topic_data)
    print(f"\n  Prompt built — {len(prompt):,} chars (~{len(prompt)//4:,} tokens) sent to LLM")

    # Call LLM with logging
    profile = get_profile(MODULE_NAME)
    llm = make_llm(**profile)

    response_text = call_llm(
        llm,
        prompt,
        module=MODULE_NAME,
        metadata={
            "topic": topic,
            "claims_count": claims_data["total_claims"],
            "summary_words": summary_data.get("word_count", 0),
        }
    )

    # Parse into sections
    sections = parse_enrichment_response(response_text)

    # Word counts per section
    section_words = {k: len(v.split()) for k, v in sections.items()}

    return {
        "topic": topic,
        "generated_at": datetime.now().isoformat(),
        "llm_profile": profile,
        "section_word_counts": section_words,
        "total_enrichment_words": sum(section_words.values()),
        **sections,   # background, why_it_matters, technical_breakdown, comparisons, audience_angle
    }


def save_enriched(enriched, date_str=None):
    """Save enriched context to output/layer_3_intelligence/research/"""
    ensure_output_dirs()

    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    filepath = INTEL_RESEARCH / f"enriched_{date_str}.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(enriched, f, indent=2, ensure_ascii=False)

    return filepath


def find_latest(directory, pattern):
    candidates = sorted(Path(directory).glob(pattern), reverse=True)
    return candidates[0] if candidates else None


# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add background and context beyond the source articles")
    parser.add_argument("--summary", help="Path to summary JSON")
    parser.add_argument("--claims",  help="Path to claims JSON")
    parser.add_argument("--topic",   help="Path to selected_topic JSON")
    args = parser.parse_args()

    summary_path = args.summary or find_latest(INTEL_SUMMARIES,  "summary_*.json")
    claims_path  = args.claims  or find_latest(INTEL_OUTPUT,     "claims_*.json")
    topic_path   = args.topic   or find_latest(INTEL_OUTPUT,     "selected_topic_*.json")

    if not summary_path:
        print("No summary file found. Run summarizer.py first."); sys.exit(1)
    if not claims_path:
        print("No claims file found. Run claim_extractor.py first."); sys.exit(1)
    if not topic_path:
        print("No selected_topic file found. Run topic_selector.py first."); sys.exit(1)

    # Extract date from filename
    date_str = Path(summary_path).stem.replace("summary_", "")

    print(f"Summary: {summary_path}")
    print(f"Claims:  {claims_path}")
    print(f"Topic:   {topic_path}")
    print()

    profile = get_profile(MODULE_NAME)
    print(f"LLM profile: {profile['provider']}/{profile['model']}")
    print()

    enriched = run_enricher(summary_path, claims_path, topic_path)

    filepath = save_enriched(enriched, date_str)

    # Print results
    print()
    print(f"Enrichment complete — {enriched['total_enrichment_words']} words added")
    print()
    for section, word_count in enriched["section_word_counts"].items():
        print(f"  {section:22} {word_count:4} words")

    print()
    for section in ["background", "why_it_matters", "technical_breakdown", "comparisons", "audience_angle"]:
        content = enriched.get(section, "")
        print(f"\n=== {section.upper().replace('_', ' ')} ===")
        print(content[:400] + ("..." if len(content) > 400 else ""))

    print()
    print(f"Saved to: {filepath}")
    print(f"\nNext: python pipelines/layer_3_intelligence/context_builder.py")
