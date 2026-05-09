"""
Layer 1 Orchestrator — Run All Extraction Collectors

Runs all enabled collectors in sequence and produces a single master file
combining ALL collected documents. Layer 2 loads just this one file.

Output:
    output/layer_1_raw/master_YYYY-MM-DD.json  — every document from every source

Usage:
    python run_extraction.py                   # run all collectors
    python run_extraction.py --skip-youtube     # skip YouTube (slow, uses API quota)
"""

import sys
import json
import argparse
from datetime import datetime

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
from config.paths import RAW_OUTPUT, ensure_output_dirs

# Import all collectors
from pipelines.layer_1_extraction.arxiv_collector import fetch_arxiv_papers
from pipelines.layer_1_extraction.hackernews_collector import fetch_ai_stories
from pipelines.layer_1_extraction.newsapi_collector import fetch_news as fetch_newsapi
from pipelines.layer_1_extraction.newsdata_collector import fetch_news as fetch_newsdata
from pipelines.layer_1_extraction.mediastack_collector import fetch_news as fetch_mediastack
from pipelines.layer_1_extraction.github_collector import fetch_trending_repos
from pipelines.layer_1_extraction.company_blogs.openai_blog import fetch_posts as fetch_openai
from pipelines.layer_1_extraction.company_blogs.anthropic_blog import fetch_posts as fetch_anthropic


def run_all(skip_youtube=False):
    """
    Run all extraction collectors and return combined list of documents.
    Each collector handles its own API calls — we just call and merge.
    """
    all_docs = []
    summary = []

    # ── arXiv (multiple categories) ──
    print("[arXiv] Fetching cs.AI, cs.LG, cs.CL papers...")
    for category in ["cs.AI", "cs.LG", "cs.CL"]:
        papers = fetch_arxiv_papers(category=category, max_results=10)
        all_docs.extend(papers)
    summary.append(f"arXiv: {sum(1 for d in all_docs if d['module'] == 'arxiv_collector')} papers")

    # ── Hacker News ──
    print("[HackerNews] Scanning top stories for AI content...")
    hn_stories = fetch_ai_stories(story_type="top", max_stories=20, scan_depth=100)
    all_docs.extend(hn_stories)
    summary.append(f"HackerNews: {len(hn_stories)} stories")

    # ── NewsAPI ──
    print("[NewsAPI] Searching for AI news...")
    for query in ["artificial intelligence", "LLM AI agent", "OpenAI Anthropic Google AI"]:
        articles = fetch_newsapi(query=query, max_results=10, days_back=2)
        all_docs.extend(articles)
    summary.append(f"NewsAPI: {sum(1 for d in all_docs if d['module'] == 'newsapi_collector')} articles")

    # ── Newsdata.io ──
    print("[Newsdata] Searching for AI news...")
    for query in ["artificial intelligence", "generative AI LLM"]:
        articles = fetch_newsdata(query=query, max_results=10)
        all_docs.extend(articles)
    summary.append(f"Newsdata: {sum(1 for d in all_docs if d['module'] == 'newsdata_collector')} articles")

    # ── Mediastack ──
    print("[Mediastack] Searching for AI news...")
    articles = fetch_mediastack(query="artificial intelligence", max_results=25)
    all_docs.extend(articles)
    summary.append(f"Mediastack: {len(articles)} articles")

    # ── GitHub ──
    print("[GitHub] Fetching trending AI repos (with READMEs)...")
    for query in ["LLM", "AI agent", "machine learning"]:
        repos = fetch_trending_repos(query=query, max_results=5, days_back=7, include_readme=True)
        all_docs.extend(repos)
    summary.append(f"GitHub: {sum(1 for d in all_docs if d['module'] == 'github_collector')} repos")

    # ── OpenAI Blog ──
    print("[OpenAI Blog] Fetching latest posts...")
    openai_posts = fetch_openai(max_results=10)
    all_docs.extend(openai_posts)
    summary.append(f"OpenAI Blog: {len(openai_posts)} posts")

    # ── Anthropic Blog ──
    print("[Anthropic Blog] Fetching latest posts (with full text)...")
    anthropic_posts = fetch_anthropic(max_results=10, include_full_text=True)
    all_docs.extend(anthropic_posts)
    summary.append(f"Anthropic Blog: {len(anthropic_posts)} posts")

    # ── YouTube (optional — slow, costs API quota) ──
    if not skip_youtube:
        print("[YouTube] Skipped by default. Use --all-channels via youtube_collector.py directly.")
        summary.append("YouTube: skipped (run youtube_collector.py --all-channels separately)")
    else:
        summary.append("YouTube: skipped (--skip-youtube)")

    return all_docs, summary


def save_master_file(all_docs):
    """Save all documents into one master JSON file."""
    ensure_output_dirs()

    date_str = datetime.now().strftime("%Y-%m-%d")
    filepath = RAW_OUTPUT / f"master_{date_str}.json"

    master = {
        "generated_at": datetime.now().isoformat(),
        "total_documents": len(all_docs),
        "sources": {},
        "documents": all_docs,
    }

    # Count by source module
    for doc in all_docs:
        module = doc.get("module", "unknown")
        master["sources"][module] = master["sources"].get(module, 0) + 1

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(master, f, indent=2, ensure_ascii=False)

    return filepath


# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run all Layer 1 extraction collectors")
    parser.add_argument("--skip-youtube", action="store_true", help="Skip YouTube collector")
    args = parser.parse_args()

    print("=" * 60)
    print("  Layer 1 — Full Extraction Run")
    print("=" * 60)
    print()

    all_docs, summary = run_all(skip_youtube=args.skip_youtube)

    filepath = save_master_file(all_docs)

    print()
    print("=" * 60)
    print("  Summary")
    print("=" * 60)
    for line in summary:
        print(f"  {line}")
    print(f"\n  TOTAL: {len(all_docs)} documents")
    print(f"  Master file: {filepath}")
    print("=" * 60)
