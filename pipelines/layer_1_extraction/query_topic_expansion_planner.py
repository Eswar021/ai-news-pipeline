"""
Module: query_topic_expansion_planner
Layer: 1 — Source Extraction
Purpose: Expand the run manifest's query_themes into collector-specific query strings.
         Each source type needs different query logic — news APIs need boolean strings,
         arXiv needs categories, GitHub needs topics, community needs keywords.

Run standalone:
    python query_topic_expansion_planner.py
    python query_topic_expansion_planner.py --themes "AI agents" "LLM releases"
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Company and product names to include as entity aliases in queries
_ENTITY_ALIASES = [
    "OpenAI", "Anthropic", "Google DeepMind", "Meta AI", "Mistral",
    "Hugging Face", "NVIDIA", "Microsoft", "Amazon",
    "GPT-4", "Claude", "Gemini", "Llama", "Grok",
]

# Map of theme → arXiv keywords
_THEME_TO_ARXIV_KEYWORDS = {
    "AI agents":       ["agentic AI", "autonomous agent", "tool use", "ReAct"],
    "LLM releases":    ["large language model", "foundation model", "pretraining"],
    "AI coding tools": ["code generation", "program synthesis", "software engineering AI"],
    "open-source AI":  ["open source model", "open weights", "open LLM"],
    "AI regulation":   ["AI policy", "AI governance", "responsible AI"],
    "AI chips":        ["AI hardware", "GPU", "TPU", "neural processing unit"],
    "AI research":     ["transformer", "attention mechanism", "RLHF", "alignment"],
    "multimodal AI":   ["multimodal", "vision language model", "VLM"],
    "AI safety":       ["AI safety", "alignment", "red teaming", "jailbreak"],
    "foundation models": ["foundation model", "pretraining", "scaling law"],
}

# GitHub topic tags to search
_GITHUB_TOPICS = [
    "llm", "ai-agents", "rag", "transformers", "code-generation",
    "langchain", "openai", "llama", "vector-database", "ai-safety",
]

# Reddit subreddits to pull from
_SUBREDDITS = [
    "MachineLearning", "LocalLLaMA", "OpenAI", "ClaudeAI",
    "artificial", "singularity", "AIdev",
]


def expand_queries(query_themes: list, source_groups: list) -> dict:
    """
    Convert run manifest query_themes into per-source-group query plans.

    Returns:
        dict keyed by source_group name, each value is a list of query strings / params
    """
    plan = {}

    if "tech_news_apis" in source_groups:
        entity_str = " OR ".join(f'"{e}"' for e in _ENTITY_ALIASES[:8])
        theme_terms = " OR ".join(f'"{t}"' for t in query_themes[:5])
        plan["tech_news_apis"] = [
            "(artificial intelligence OR generative AI OR LLM OR AI agent)",
            f"({entity_str})",
            f"({theme_terms})",
        ]

    if "research_papers" in source_groups:
        arxiv_kw = []
        for theme in query_themes:
            arxiv_kw.extend(_THEME_TO_ARXIV_KEYWORDS.get(theme, [theme]))
        # Deduplicate while preserving order
        seen = set()
        unique_kw = [k for k in arxiv_kw if not (k in seen or seen.add(k))]
        plan["research_papers"] = {
            "categories": ["cs.AI", "cs.LG", "cs.CL", "cs.CV"],
            "keywords": unique_kw[:10],
        }

    if "community_signals" in source_groups:
        plan["community_signals"] = {
            "hackernews_keywords": [e.lower() for e in _ENTITY_ALIASES[:6]] + ["ai agent", "llm", "open source ai"],
            "reddit_subreddits": _SUBREDDITS,
            "reddit_keywords": query_themes,
        }

    if "github_open_source_signals" in source_groups:
        plan["github_open_source_signals"] = {
            "topics": _GITHUB_TOPICS,
            "keywords": [t.lower().replace(" ", "-") for t in query_themes[:5]],
            "sort": "stars",
            "min_stars": 100,
        }

    if "ai_company_blogs" in source_groups:
        # Company blogs don't need query strings — we fetch their RSS/listing directly
        plan["ai_company_blogs"] = {"mode": "rss_or_html_listing", "filter_keywords": query_themes}

    if "youtube_podcast_transcripts" in source_groups:
        plan["youtube_podcast_transcripts"] = {
            "search_query": " ".join(query_themes[:3]),
            "keywords": query_themes,
        }

    return plan


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Expand query themes into per-source query plans")
    parser.add_argument(
        "--themes", nargs="+",
        default=["AI agents", "LLM releases", "AI coding tools", "open-source AI", "AI research"],
        help="Query themes to expand",
    )
    parser.add_argument(
        "--groups", nargs="+",
        default=["tech_news_apis", "research_papers", "community_signals", "github_open_source_signals", "ai_company_blogs"],
        help="Source groups to generate queries for",
    )
    args = parser.parse_args()

    print(f"\nExpanding {len(args.themes)} themes for {len(args.groups)} source groups...\n")
    plan = expand_queries(args.themes, args.groups)

    print(json.dumps(plan, indent=2))
    print(f"\nGenerated query plans for: {list(plan.keys())}")
