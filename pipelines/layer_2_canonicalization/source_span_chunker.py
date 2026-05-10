"""
Layer 2 — Module 7: Source Span Chunker

Splits clean text into exact, citeable source spans.
This module also contains the source-type routing logic (which chunking
strategy to use per source_group) — no separate router module needed.

Chunking strategies by source_group:
  ai_company_blogs         — sentence groups, ~250 tokens per span
  research_papers          — 1–3 spans over abstract, sentence-based
  tech_news_apis           — single span (already a short snippet)
  community_signals        — single metadata span (title + engagement)
  github_open_source_signals — heading sections or single span
  youtube_podcast_transcripts — timestamp windows (30–90s)

IMPORTANT rules (from design doc):
  - Do not rewrite source text.
  - Do not summarize source text.
  - Do not merge unrelated sections.
  - Do not create claim text here — only mark is_claim_candidate.

Usage:
    python source_span_chunker.py --run-id run_2026_05_10_48h_auto
"""

import sys
import re
import json
import argparse
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"])")
_APPROX_CHARS_PER_TOKEN = 5.5   # rough estimate for English


def _token_estimate(text: str) -> int:
    return max(1, int(len(text) / _APPROX_CHARS_PER_TOKEN))


def _split_sentences(text: str) -> list[str]:
    """Split flat text into sentences."""
    parts = _SENTENCE_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def _group_sentences(sentences: list[str], max_tokens: int = 250) -> list[str]:
    """Group sentences into chunks that fit within max_tokens."""
    chunks = []
    current = []
    current_tokens = 0

    for sent in sentences:
        t = _token_estimate(sent)
        if current_tokens + t > max_tokens and current:
            chunks.append(" ".join(current))
            current = [sent]
            current_tokens = t
        else:
            current.append(sent)
            current_tokens += t

    if current:
        chunks.append(" ".join(current))

    return [c for c in chunks if c.strip()]


def _make_span(canonical_document_id: str, source_id: str, source_group: str,
               canonical_url: str, trust_tier, source_role: str,
               span_index: int, span_type: str, text: str,
               char_start: int, section_heading: str = "",
               timestamp_start: Optional[float] = None,
               timestamp_end: Optional[float] = None) -> dict:
    """Build a single SourceSpan record."""
    span_id = f"span_{canonical_document_id}_{span_index:04d}"
    is_claim_candidate = (
        len(text) >= 100 and
        trust_tier in (1, 1.5, 2, 2.5) and
        source_role not in ("trend_signal_only", "not_for_claims")
    )

    span = {
        "span_id":              span_id,
        "canonical_document_id": canonical_document_id,
        "source_id":            source_id,
        "source_group":         source_group,
        "trust_tier":           trust_tier,
        "source_role":          source_role,
        "source_url":           canonical_url,
        "span_index":           span_index,
        "span_type":            span_type,
        "section_heading":      section_heading,
        "text":                 text,
        "char_start":           char_start,
        "char_end":             char_start + len(text),
        "token_estimate":       _token_estimate(text),
        "is_claim_candidate":   is_claim_candidate,
    }

    if timestamp_start is not None:
        span["timestamp_start"] = timestamp_start
        span["timestamp_end"]   = timestamp_end

    return span


def chunk(canonical_document_id: str, clean_text: str,
          source_group: str, source_id: str,
          canonical_url: str, trust_tier, source_role: str,
          content_completeness: str = "full",
          title: str = "",
          item: dict = None) -> list[dict]:
    """
    Chunk clean_text into source spans based on source_group.

    Args:
        canonical_document_id: From canonical_url_resolver
        clean_text:            Cleaned text from content_cleaner
        source_group:          e.g. "research_papers"
        source_id:             e.g. "arxiv_cs_ai"
        canonical_url:         Canonical URL for citation
        trust_tier:            From trust_tier_tagger
        source_role:           From trust_tier_tagger
        content_completeness:  From content_quality_classifier
        title:                 Document title
        item:                  Full item dict (for community/GitHub metadata)

    Returns:
        List of SourceSpan dicts.
    """
    item = item or {}
    spans = []

    def _base(idx, span_type, text, char_start, heading="", ts_start=None, ts_end=None):
        return _make_span(
            canonical_document_id, source_id, source_group, canonical_url,
            trust_tier, source_role, idx, span_type, text, char_start,
            heading, ts_start, ts_end,
        )

    # ── community_signals ─────────────────────────────────────────────────────
    if source_group == "community_signals":
        score         = item.get("score", 0)
        comment_count = item.get("comment_count", 0)
        hn_url        = item.get("hn_discussion_url", "")
        signal_type   = item.get("signal_type", "")
        linked_url    = item.get("url", canonical_url)

        meta_text = f"{title}"
        if score:
            meta_text += f" [score: {score}, comments: {comment_count}]"
        if signal_type:
            meta_text += f" [type: {signal_type}]"
        if linked_url and linked_url != canonical_url:
            meta_text += f" [linked: {linked_url}]"

        spans.append(_base(0, "community_metadata", meta_text, 0))
        return spans

    # ── tech_news_apis ────────────────────────────────────────────────────────
    if source_group == "tech_news_apis":
        if not clean_text:
            if title:
                spans.append(_base(0, "headline_only", title, 0))
            return spans

        description = item.get("description", "")
        combined = clean_text
        if description and description not in clean_text:
            combined = description + " " + clean_text

        spans.append(_base(0, "news_snippet", combined.strip(), 0))
        return spans

    # ── research_papers ───────────────────────────────────────────────────────
    if source_group == "research_papers":
        if not clean_text:
            if title:
                spans.append(_base(0, "title_only", title, 0))
            return spans

        sentences = _split_sentences(clean_text)
        chunks    = _group_sentences(sentences, max_tokens=180)

        char_pos = 0
        for i, chunk_text in enumerate(chunks[:3]):    # max 3 spans for an abstract
            spans.append(_base(i, "abstract_segment", chunk_text, char_pos, "Abstract"))
            char_pos += len(chunk_text) + 1
        return spans

    # ── github_open_source_signals ────────────────────────────────────────────
    if source_group == "github_open_source_signals":
        stars   = item.get("stars", item.get("stargazers_count", ""))
        forks   = item.get("forks", "")
        topics  = item.get("topics", [])
        desc    = item.get("description", "") or ""

        meta_parts = [title]
        if desc:
            meta_parts.append(desc)
        if stars:
            meta_parts.append(f"Stars: {stars}")
        if forks:
            meta_parts.append(f"Forks: {forks}")
        if topics:
            meta_parts.append(f"Topics: {', '.join(topics[:5])}")

        meta_text = " | ".join(p for p in meta_parts if p)
        spans.append(_base(0, "repo_metadata", meta_text, 0, "Repository Metadata"))

        if clean_text and len(clean_text) > 200:
            sentences = _split_sentences(clean_text)
            chunks    = _group_sentences(sentences, max_tokens=300)
            char_pos  = 0
            for i, chunk_text in enumerate(chunks[:5]):
                spans.append(_base(i + 1, "readme_section", chunk_text, char_pos, "README"))
                char_pos += len(chunk_text) + 1

        return spans

    # ── youtube_podcast_transcripts ───────────────────────────────────────────
    if source_group == "youtube_podcast_transcripts":
        transcript_blocks = item.get("transcript_blocks") or \
                            (item.get("content", {}) or {}).get("transcript_blocks") or []

        if transcript_blocks:
            current_texts  = []
            current_start  = None
            current_end    = None
            current_tokens = 0
            span_idx       = 0
            MAX_TOKENS     = 180

            for block in transcript_blocks:
                t = block.get("text", "").strip()
                if not t:
                    continue
                ts  = block.get("start", 0)
                te  = block.get("end", ts)
                tok = _token_estimate(t)

                if current_tokens + tok > MAX_TOKENS and current_texts:
                    combined = " ".join(current_texts)
                    spans.append(_base(span_idx, "transcript_segment", combined, 0,
                                       "", current_start, current_end))
                    span_idx += 1
                    current_texts  = [t]
                    current_start  = ts
                    current_end    = te
                    current_tokens = tok
                else:
                    if current_start is None:
                        current_start = ts
                    current_end = te
                    current_texts.append(t)
                    current_tokens += tok

            if current_texts:
                combined = " ".join(current_texts)
                spans.append(_base(span_idx, "transcript_segment", combined, 0,
                                   "", current_start, current_end))
            return spans

        # No transcript blocks — treat as text
        if clean_text:
            sentences = _split_sentences(clean_text)
            chunks    = _group_sentences(sentences, max_tokens=180)
            char_pos  = 0
            for i, c in enumerate(chunks):
                spans.append(_base(i, "transcript_segment", c, char_pos))
                char_pos += len(c) + 1
        elif title:
            spans.append(_base(0, "title_only", title, 0))
        return spans

    # ── ai_company_blogs (default for long text) ──────────────────────────────
    if not clean_text:
        if title:
            spans.append(_base(0, "title_only", title, 0))
        return spans

    sentences = _split_sentences(clean_text)
    chunks    = _group_sentences(sentences, max_tokens=250)

    char_pos = 0
    for i, chunk_text in enumerate(chunks):
        spans.append(_base(i, "paragraph_group", chunk_text, char_pos))
        char_pos += len(chunk_text) + 1

    return spans


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=False)
    args = parser.parse_args()

    from pipelines.layer_2_canonicalization.content_cleaner import clean as clean_fn
    from pipelines.layer_2_canonicalization.trust_tier_tagger import tag as tag_fn
    from pipelines.layer_2_canonicalization.content_quality_classifier import classify as classify_fn

    if args.run_id:
        run_id = args.run_id
    else:
        run_dirs = sorted(RUNS_DIR.glob("*/run_manifest.json"),
                          key=lambda p: p.stat().st_mtime, reverse=True)
        run_id = run_dirs[0].parent.name
        print(f"Auto-discovered run: {run_id}")

    raw_path = RUNS_DIR / run_id / "layer_1" / "raw_documents.jsonl"
    docs = [json.loads(l) for l in raw_path.read_text().splitlines() if l.strip()]

    print(f"\nSource Span Chunker — {run_id}")
    seen = set()
    for doc in docs:
        sg = doc["source"]["source_group"]
        if sg in seen:
            continue
        seen.add(sg)

        title   = doc["item"].get("title", "")
        raw     = doc["content"].get("raw_text", "")
        ca      = doc["content"].get("content_available", "")
        cleaned = clean_fn(raw, sg, title)["clean_text"]
        quality = classify_fn(cleaned, sg, ca, title)
        trust   = tag_fn(doc, quality["content_completeness"])

        spans = chunk(
            canonical_document_id="doc_test_001",
            clean_text=cleaned,
            source_group=sg,
            source_id=doc["source"]["source_id"],
            canonical_url=doc["item"].get("url", ""),
            trust_tier=trust["trust_tier"],
            source_role=trust["source_role"],
            content_completeness=quality["content_completeness"],
            title=title,
            item=doc["item"],
        )

        print(f"  [{sg}]  {len(spans)} spans")
        for s in spans[:2]:
            print(f"    span {s['span_index']} ({s['span_type']})  is_claim={s['is_claim_candidate']}")
            print(f"    {s['text'][:120]}...")
        print()
