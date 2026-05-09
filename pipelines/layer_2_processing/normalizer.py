"""
Normalizer — Layer 2, Module 1

Takes the master JSON file from Layer 1 (153 docs with mixed schemas)
and produces a normalized file where every document has the exact same fields.

Key things it does:
  - Standardize date formats to ISO 8601
  - Fill missing fields with sensible defaults
  - Strip any leftover HTML from raw_text
  - Extract entities (company/model names) from title + description via keyword matching
  - Unify score fields (HN upvotes, GitHub stars) into one community_score
  - Truncate oversized raw_text (e.g. 70k GitHub READMEs) to a reasonable length

Usage:
    python normalizer.py                                       # uses today's master file
    python normalizer.py --input output/layer_1_raw/master_2026-05-08.json
"""

import sys
import json
import re
import argparse
from datetime import datetime, timezone
from pathlib import Path
from html.parser import HTMLParser

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.paths import RAW_OUTPUT, PROCESSED_DOCS, ensure_output_dirs


# ── Entity dictionaries ──────────────────────────────────────────────────────

MAJOR_COMPANIES = [
    "OpenAI", "Anthropic", "Google", "DeepMind", "Google DeepMind",
    "Meta", "Microsoft", "NVIDIA", "Apple", "Amazon", "AWS",
    "Hugging Face", "HuggingFace", "Mistral", "Cohere", "Stability AI",
    "xAI", "Tesla", "Samsung", "Intel", "AMD", "Qualcomm",
    "Cloudflare", "Databricks", "Snowflake", "Salesforce",
]

KNOWN_MODELS = [
    "GPT-5", "GPT-4", "GPT-4o", "GPT-3", "o1", "o3",
    "Claude", "Claude Opus", "Claude Sonnet", "Claude Haiku",
    "Gemini", "Gemma", "PaLM",
    "Llama", "Llama 3", "Llama 4",
    "Mistral", "Mixtral",
    "DALL-E", "Midjourney", "Stable Diffusion", "Sora", "Flux",
    "Copilot", "ChatGPT", "Grok",
    "DeepSeek", "Qwen", "Phi",
    "Whisper", "CLIP", "SAM",
    "AlphaFold", "AlphaGo", "AlphaEvolve",
]

AI_KEYWORDS = [
    "LLM", "transformer", "diffusion", "neural network", "deep learning",
    "machine learning", "reinforcement learning", "fine-tuning", "RAG",
    "AI agent", "agentic", "multi-modal", "multimodal",
    "embedding", "vector database", "prompt engineering",
    "open source", "open-source", "API", "SDK",
]

# Pre-compile patterns for faster matching
_COMPANY_PATTERNS = [(c, re.compile(re.escape(c), re.IGNORECASE)) for c in MAJOR_COMPANIES]
_MODEL_PATTERNS   = [(m, re.compile(re.escape(m), re.IGNORECASE)) for m in KNOWN_MODELS]
_KEYWORD_PATTERNS = [(k, re.compile(re.escape(k), re.IGNORECASE)) for k in AI_KEYWORDS]


# ── HTML stripper ─────────────────────────────────────────────────────────────

class _TextStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []
    def handle_data(self, data):
        self._parts.append(data)
    def get_text(self):
        return " ".join(self._parts)

def strip_html(text):
    if not text or "<" not in text:
        return text
    s = _TextStripper()
    s.feed(text)
    return s.get_text().strip()


# ── Date normalizer ───────────────────────────────────────────────────────────

def normalize_date(raw_date):
    """
    Try to parse various date formats into ISO 8601.
    Returns the original string if parsing fails — don't crash on bad dates.
    """
    if not raw_date:
        return ""

    # Already ISO format
    if re.match(r"\d{4}-\d{2}-\d{2}T", raw_date):
        return raw_date

    # "Thu, 07 May 2026 11:00:00 +0000" — RSS style
    for fmt in [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%b %d, %Y",
    ]:
        try:
            dt = datetime.strptime(raw_date.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue

    return raw_date  # return as-is if nothing worked


# ── Entity extraction ─────────────────────────────────────────────────────────

def extract_entities(title, description="", raw_text_sample=""):
    """
    Extract company names, model names, and AI keywords from text.
    Uses keyword matching — no LLM needed.

    We check title + description + first 500 chars of raw_text.
    Title matches are weighted more (they appear in the headline).
    """
    search_text = f"{title} {description} {raw_text_sample[:500]}"

    companies = []
    for name, pattern in _COMPANY_PATTERNS:
        if pattern.search(search_text):
            companies.append(name)

    models = []
    for name, pattern in _MODEL_PATTERNS:
        if pattern.search(search_text):
            models.append(name)

    keywords = []
    for name, pattern in _KEYWORD_PATTERNS:
        if pattern.search(search_text):
            keywords.append(name)

    return {
        "companies": companies,
        "models": models,
        "keywords": keywords,
    }


# ── Main normalizer ──────────────────────────────────────────────────────────

MAX_RAW_TEXT_LEN = 15000   # Truncate massive READMEs / articles to 15k chars

def normalize_document(doc):
    """
    Map any source document to the unified schema.
    Every field gets a value — no missing keys.
    """
    title       = strip_html(doc.get("title", "")) or ""
    url         = doc.get("url", "") or ""
    description = strip_html(doc.get("description", "") or doc.get("abstract", "") or "")
    raw_text    = strip_html(doc.get("raw_text", "")) or ""
    author      = doc.get("author", "") or doc.get("authors", "") or ""

    # If author is a list (arXiv), join it
    if isinstance(author, list):
        author = ", ".join(author)

    # Truncate massive raw_text
    if len(raw_text) > MAX_RAW_TEXT_LEN:
        raw_text = raw_text[:MAX_RAW_TEXT_LEN] + "... [truncated]"

    # Community score: HN upvotes or GitHub stars
    community_score = doc.get("score", 0) or doc.get("stars", 0) or 0
    comment_count   = doc.get("comment_count", 0) or 0

    # Publisher
    publisher = doc.get("publisher", "") or doc.get("company", "") or doc.get("source_id", "") or ""

    # Categories: merge arXiv categories, GitHub topics, newsdata categories
    categories = doc.get("categories", []) or doc.get("topics", []) or []
    if isinstance(categories, str):
        categories = [categories]

    # Extract entities
    entities = extract_entities(title, description, raw_text)

    return {
        "document_id":    doc.get("document_id", ""),
        "source_id":      doc.get("source_id", ""),
        "module":         doc.get("module", ""),
        "source_type":    doc.get("source_type", ""),
        "trust_tier":     doc.get("trust_tier", 3),
        "title":          title,
        "url":            url,
        "published_at":   normalize_date(doc.get("published_at", "")),
        "author":         author,
        "publisher":      publisher,
        "description":    description,
        "raw_text":       raw_text,
        "content_hash":   doc.get("content_hash", ""),
        "collected_at":   doc.get("collected_at", ""),
        "community_score": community_score,
        "comment_count":  comment_count,
        "categories":     categories,
        "entities":       entities,
    }


def normalize_all(master_path):
    """
    Load the master file, normalize every document, return the list.
    """
    data = json.loads(Path(master_path).read_text(encoding="utf-8"))
    raw_docs = data.get("documents", [])

    normalized = []
    for doc in raw_docs:
        normalized.append(normalize_document(doc))

    return normalized


def save_normalized(docs, date_str=None):
    """Save normalized documents to output/layer_2_processed/documents/"""
    ensure_output_dirs()

    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    filepath = PROCESSED_DOCS / f"normalized_{date_str}.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(docs, f, indent=2, ensure_ascii=False)

    return filepath


# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Normalize Layer 1 master file")
    parser.add_argument("--input", help="Path to master JSON (default: today's)")
    args = parser.parse_args()

    if args.input:
        master_path = args.input
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")
        master_path = RAW_OUTPUT / f"master_{date_str}.json"

    print(f"Loading master file: {master_path}")
    docs = normalize_all(master_path)

    # Stats
    entity_counts = {"companies": 0, "models": 0, "keywords": 0}
    for d in docs:
        for key in entity_counts:
            if d["entities"][key]:
                entity_counts[key] += 1

    print(f"Normalized {len(docs)} documents")
    print(f"  Docs with company entities: {entity_counts['companies']}")
    print(f"  Docs with model entities:   {entity_counts['models']}")
    print(f"  Docs with AI keywords:      {entity_counts['keywords']}")
    print()

    # Show a few examples
    for d in docs[:3]:
        print(f"  [{d['module'][:15]:15}] {d['title'][:60]}")
        print(f"    entities: {d['entities']}")
        print()

    filepath = save_normalized(docs)
    print(f"Saved to: {filepath}")
