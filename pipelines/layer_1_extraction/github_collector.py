"""
GitHub Collector — Layer 1 Extraction

Fetches trending AI repositories from GitHub using their search API.
Also fetches each repo's README.md for richer context (needed for script writing).
Works without a token (60 req/hr), better with GITHUB_TOKEN in .env (5000 req/hr).

Usage:
    python github_collector.py                         # default: AI topics, fetches READMEs
    python github_collector.py --query "LLM agent" --max 10
    python github_collector.py --no-readme             # skip README fetch (faster)
"""

import os
import sys
import json
import hashlib
import argparse
from datetime import datetime, timezone, timedelta
from config.time_utils import now_project
from config.time_utils import now_project_iso
from urllib.request import urlopen, Request
from urllib.parse import urlencode

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
from config.paths import RAW_GITHUB, ensure_output_dirs
from dotenv import load_dotenv

load_dotenv()


GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
GITHUB_API_BASE   = "https://api.github.com"


def _make_headers():
    """Build request headers. Adds Authorization if GITHUB_TOKEN is set."""
    headers = {
        "User-Agent": "AI-Content-Creation/1.0",
        "Accept": "application/vnd.github.v3+json",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def fetch_readme(owner, repo_name):
    """
    Fetch the README.md raw markdown text for a GitHub repo.

    Uses Accept: application/vnd.github.v3.raw so GitHub returns the raw
    markdown directly instead of a base64-encoded JSON wrapper.

    Returns empty string if the repo has no README or the request fails.
    """
    headers = _make_headers()
    headers["Accept"] = "application/vnd.github.v3.raw"

    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo_name}/readme"
    req = Request(url, headers=headers)
    response = urlopen(req, timeout=15)
    return response.read().decode("utf-8")


def fetch_trending_repos(query="artificial intelligence", max_results=10, days_back=7, include_readme=True):
    """
    Fetch trending AI repositories from GitHub search API.

    Args:
        query:          Search query string
        max_results:    Max repos to return (max 30 per page without pagination)
        days_back:      Only repos pushed in last N days
        include_readme: If True, also fetch each repo's README.md

    Returns:
        List of repo dicts in our standard document format.
    """
    since_date = (now_project() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    search_q = f"{query} pushed:>{since_date}"

    params = {
        "q": search_q,
        "sort": "stars",
        "order": "desc",
        "per_page": min(max_results, 30),
    }

    url = f"{GITHUB_SEARCH_URL}?{urlencode(params)}"
    req = Request(url, headers=_make_headers())
    response = urlopen(req, timeout=15)
    data = json.loads(response.read().decode("utf-8"))

    repos = []
    for raw in data.get("items", []):
        doc = parse_repo(raw, query, include_readme=include_readme)
        repos.append(doc)

    return repos


def parse_repo(raw, query_used, include_readme=True):
    """Convert a GitHub repo search result into our standard document format."""

    full_name   = raw.get("full_name", "") or ""
    url         = raw.get("html_url", "") or ""
    description = raw.get("description", "") or ""
    language    = raw.get("language", "") or ""
    stars       = raw.get("stargazers_count", 0)
    forks       = raw.get("forks_count", 0)
    open_issues = raw.get("open_issues_count", 0)
    watchers    = raw.get("watchers_count", 0)
    created_at  = raw.get("created_at", "") or ""
    updated_at  = raw.get("updated_at", "") or ""
    pushed_at   = raw.get("pushed_at", "") or ""
    topics      = raw.get("topics", []) or []
    license_info = (raw.get("license") or {}).get("spdx_id", "")
    owner       = (raw.get("owner") or {}).get("login", "")
    repo_name   = full_name.split("/")[-1] if "/" in full_name else full_name

    # Fetch README — this is the main content payload for this source type.
    # Description is only 1 line; README has what the project actually does,
    # its features, benchmarks, comparisons, and usage — needed for script writing.
    readme_text = ""
    if include_readme and owner and repo_name:
        readme_text = fetch_readme(owner, repo_name)

    content_hash = hashlib.sha256(f"github:{full_name}".encode()).hexdigest()[:16]

    return {
        "document_id": f"github_{content_hash}",
        "source_id": "github_trending_ai",
        "module": "github_collector",
        "source_type": "community_signal",
        "trust_tier": 3,
        "title": full_name,
        "url": url,
        "published_at": pushed_at,
        "created_at": created_at,
        "updated_at": updated_at,
        "author": owner,
        "description": description,
        "readme_text": readme_text,
        "raw_text": readme_text or description,   # README preferred, fallback to description
        "language": language,
        "stars": stars,
        "forks": forks,
        "open_issues": open_issues,
        "watchers": watchers,
        "topics": topics,
        "license": license_info,
        "signal_type": "open_source_project",
        "query_used": query_used,
        "content_hash": content_hash,
        "collected_at": now_project_iso(),
    }


def save_results(repos, query):
    """Save collected repos to output/layer_1_raw/github/ as JSON."""
    ensure_output_dirs()

    date_str = now_project().strftime("%Y-%m-%d")
    query_slug = query.replace(" ", "_")[:30].lower()
    filename = f"{date_str}_{query_slug}.json"
    filepath = RAW_GITHUB / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(repos, f, indent=2, ensure_ascii=False)

    return filepath


# ──────────────────────────────────────────────
# Test run
# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch trending AI repos from GitHub (with READMEs)")
    parser.add_argument("--query", default="artificial intelligence", help="Search query")
    parser.add_argument("--max", type=int, default=5, help="Max results (default: 5)")
    parser.add_argument("--days", type=int, default=7, help="Days back to search (default: 7)")
    parser.add_argument("--no-readme", action="store_true", help="Skip README fetching (faster)")
    args = parser.parse_args()

    include_readme = not args.no_readme
    print(f"Fetching top {args.max} GitHub repos for '{args.query}' (last {args.days} days, readme={'yes' if include_readme else 'no'})...")
    repos = fetch_trending_repos(query=args.query, max_results=args.max, days_back=args.days, include_readme=include_readme)

    print(f"\nFound {len(repos)} repositories:\n")
    for i, r in enumerate(repos, 1):
        readme_len = len(r.get("readme_text", ""))
        print(f"  {i}. [{r['stars']}⭐ {r['forks']}🍴] {r['title']}")
        print(f"     Desc: {r['description'][:70]}")
        print(f"     Topics: {', '.join(r['topics'][:5])}")
        print(f"     README: {readme_len} chars fetched")
        print(f"     URL: {r['url']}")
        print()

    filepath = save_results(repos, args.query)
    print(f"Saved to: {filepath}")
