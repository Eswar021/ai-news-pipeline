"""
arXiv Collector — Layer 1 Extraction

Fetches recent AI/ML papers from arXiv using their public API.
No API key required. Returns structured paper metadata.

Usage:
    python arxiv_collector.py                          # default: cs.AI, 10 results
    python arxiv_collector.py --category cs.LG --max 25
"""

import sys
import json
import hashlib
import argparse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from config.time_utils import now_project
from config.time_utils import now_project_iso
from urllib.request import urlopen, Request
from urllib.parse import urlencode

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
from config.paths import RAW_ARXIV, ensure_output_dirs


ARXIV_API_URL = "http://export.arxiv.org/api/query"

# Namespace map for parsing Atom XML
NS = {
    "atom":    "http://www.w3.org/2005/Atom",
    "arxiv":   "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}


def fetch_arxiv_papers(category="cs.AI", max_results=10, sort_by="submittedDate", sort_order="descending"):
    """
    Fetch recent papers from arXiv for a given category.
    
    Args:
        category:     arXiv category (cs.AI, cs.LG, cs.CL, cs.CV, etc.)
        max_results:  Number of papers to fetch (max 100 per request)
        sort_by:      "submittedDate", "lastUpdatedDate", or "relevance"
        sort_order:   "descending" or "ascending"
    
    Returns:
        List of paper dicts in our standard document format.
    """
    params = {
        "search_query": f"cat:{category}",
        "start": 0,
        "max_results": max_results,
        "sortBy": sort_by,
        "sortOrder": sort_order,
    }

    url = f"{ARXIV_API_URL}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "AI-Content-Creation/1.0"})
    
    response = urlopen(req, timeout=30)
    xml_data = response.read().decode("utf-8")

    root = ET.fromstring(xml_data)
    entries = root.findall("atom:entry", NS)

    papers = []
    for entry in entries:
        paper = parse_entry(entry, category)
        papers.append(paper)

    return papers


def parse_entry(entry, query_category):
    """Parse a single Atom entry into our standard document format."""
    
    # Extract basic fields
    title = entry.findtext("atom:title", "", NS).strip().replace("\n", " ")
    abstract = entry.findtext("atom:summary", "", NS).strip().replace("\n", " ")
    published = entry.findtext("atom:published", "", NS).strip()
    updated = entry.findtext("atom:updated", "", NS).strip()
    arxiv_id = entry.findtext("atom:id", "", NS).strip()

    # Extract authors
    authors = []
    for author_el in entry.findall("atom:author", NS):
        name = author_el.findtext("atom:name", "", NS).strip()
        if name:
            authors.append(name)

    # Extract categories
    categories = []
    for cat_el in entry.findall("atom:category", NS):
        term = cat_el.get("term", "")
        if term:
            categories.append(term)

    # Extract links (pdf, html)
    pdf_url = ""
    html_url = ""
    for link_el in entry.findall("atom:link", NS):
        href = link_el.get("href", "")
        link_type = link_el.get("type", "")
        link_title = link_el.get("title", "")
        if link_title == "pdf" or "pdf" in href:
            pdf_url = href
        elif link_type == "text/html" or link_el.get("rel") == "alternate":
            html_url = href

    # Extract arXiv-specific fields
    comment = entry.findtext("arxiv:comment", "", NS).strip()
    journal_ref = entry.findtext("arxiv:journal_ref", "", NS).strip()
    doi = entry.findtext("arxiv:doi", "", NS).strip()
    primary_category = ""
    primary_el = entry.find("arxiv:primary_category", NS)
    if primary_el is not None:
        primary_category = primary_el.get("term", "")

    # Build content hash for dedup
    content_hash = hashlib.sha256(f"{arxiv_id}:{title}".encode()).hexdigest()[:16]

    return {
        "document_id": f"arxiv_{arxiv_id.split('/')[-1].replace('.', '_')}",
        "source_id": f"arxiv_{query_category.replace('.', '_').lower()}",
        "module": "arxiv_collector",
        "source_type": "research_paper",
        "trust_tier": 1.5,
        "title": title,
        "url": html_url or arxiv_id,
        "pdf_url": pdf_url,
        "published_at": published,
        "updated_at": updated,
        "authors": authors,
        "abstract": abstract,
        "categories": categories,
        "primary_category": primary_category,
        "comment": comment,
        "journal_ref": journal_ref,
        "doi": doi,
        "content_hash": content_hash,
        "collected_at": now_project_iso(),
        "raw_text": abstract,  # for papers, abstract is the main raw text
    }


def save_results(papers, category):
    """Save collected papers to output/layer_1_raw/arxiv/ as JSON."""
    ensure_output_dirs()

    date_str = now_project().strftime("%Y-%m-%d")
    cat_slug = category.replace(".", "_").lower()
    filename = f"{date_str}_{cat_slug}.json"
    filepath = RAW_ARXIV / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(papers, f, indent=2, ensure_ascii=False)

    return filepath


# ──────────────────────────────────────────────
# Test run
# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch recent papers from arXiv")
    parser.add_argument("--category", default="cs.AI", help="arXiv category (default: cs.AI)")
    parser.add_argument("--max", type=int, default=10, help="Max results (default: 10)")
    args = parser.parse_args()

    print(f"Fetching {args.max} papers from arXiv [{args.category}]...")
    papers = fetch_arxiv_papers(category=args.category, max_results=args.max)

    print(f"Collected {len(papers)} papers:\n")
    for i, p in enumerate(papers, 1):
        print(f"  {i}. {p['title'][:80]}...")
        print(f"     Authors: {', '.join(p['authors'][:3])}")
        print(f"     Published: {p['published_at'][:10]}")
        print(f"     Categories: {', '.join(p['categories'][:3])}")
        print(f"     URL: {p['url']}")
        print()

    filepath = save_results(papers, args.category)
    print(f"Saved to: {filepath}")
