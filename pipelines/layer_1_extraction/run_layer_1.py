"""
Layer 1 Orchestrator — Source Extraction
Purpose: Read run_manifest.json from Layer 0, dispatch the right collectors based on
         enabled source groups, produce raw_documents.jsonl + extraction_manifest.json,
         and validate the output for Layer 2.

Output:
    data/runs/{run_id}/layer_1/raw_documents.jsonl       — every collected document
    data/runs/{run_id}/layer_1/extraction_manifest.json  — collection summary
    data/runs/{run_id}/layer_1/failed_sources.jsonl      — per-event audit log
    data/runs/{run_id}/layer_1/layer1_validation_report.json

Usage:
    python run_layer_1.py --run-id run_2026_05_10_48h_auto
    python run_layer_1.py --run-id run_2026_05_10_48h_auto --skip-youtube
    python run_layer_1.py --manifest path/to/run_manifest.json
"""

import sys
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

from pipelines.layer_1_extraction.source_registry_loader import (
    load_active_sources_from_manifest,
)
from pipelines.layer_1_extraction.query_topic_expansion_planner import expand_queries
from pipelines.layer_1_extraction.layer1_output_packager import build_extraction_manifest
from pipelines.layer_1_extraction.layer1_validation_gate import validate, write_report
from pipelines.layer_1_extraction.window_filter import window_days_for_fetch
from pipelines.runtime_manifest import get_collection_caps

def _load_manifest(manifest_path: Path) -> dict:
    with open(manifest_path, encoding="utf-8") as f:
        return json.load(f)


def _enabled_groups(manifest: dict) -> list:
    """Extract enabled source group names from the run manifest."""
    collection = manifest.get("collection_strategy", {})
    return collection.get("enabled_source_groups", [])


def _query_themes(manifest: dict) -> list:
    """Get query themes from the manifest."""
    collection = manifest.get("collection_strategy", {})
    return collection.get("query_themes", [])


def _window_for_group(manifest: dict, source_group: str) -> dict:
    collection = manifest.get("collection_strategy", {})
    source_windows = collection.get("source_specific_windows", {})
    return source_windows.get(source_group) or collection.get("collection_window", {})


def _window_label(window: dict) -> str:
    start = window.get("start", "?")
    end = window.get("end", "?")
    if window.get("lookback_days"):
        lookback = f"{window['lookback_days']}d"
    else:
        lookback = f"{window.get('lookback_hours', '?')}h"
    return f"{start} → {end} ({lookback})"


def _collector_caps(manifest: dict, source_group: str) -> dict:
    return get_collection_caps(manifest).get(source_group, {})


def run_layer_1(run_id: str, manifest_path: Path = None, skip_youtube: bool = False) -> dict:
    """
    Execute the full Layer 1 extraction pipeline.

    1. Load run_manifest.json
    2. Determine enabled source groups + query themes
    3. Dispatch collectors per group
    4. Package extraction_manifest.json
    5. Validate output

    Returns the extraction manifest dict.
    """
    started_at = datetime.now(timezone.utc)

    # ── 1. Locate manifest ─────────────────────────────────────────────────────
    if manifest_path is None:
        manifest_path = RUNS_DIR / run_id / "run_manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError(f"run_manifest.json not found at {manifest_path}")

    manifest = _load_manifest(manifest_path)
    print(f"[Layer 1] Run: {run_id}")
    print(f"[Layer 1] Manifest: {manifest_path}\n")

    # ── 2. Source groups + queries ─────────────────────────────────────────────
    layer1_dir     = RUNS_DIR / run_id / "layer_1"
    output_path    = layer1_dir / "raw_documents.jsonl"
    enabled_groups = _enabled_groups(manifest)
    query_themes   = _query_themes(manifest)

    if not enabled_groups:
        raise ValueError(
            "run_manifest.json is missing collection_strategy.enabled_source_groups. "
            "Rebuild the run from Layer 0."
        )
    if not query_themes:
        raise ValueError(
            "run_manifest.json is missing collection_strategy.query_themes. "
            "Rebuild the run from Layer 0."
        )

    _ = load_active_sources_from_manifest(manifest, enabled_groups=enabled_groups)

    query_plan = expand_queries(query_themes, enabled_groups)

    print(f"[Layer 1] Enabled groups: {enabled_groups}")
    print(f"[Layer 1] Query themes  : {query_themes[:3]}...")
    print(f"[Layer 1] Output        : {output_path}\n")

    # Clear any previous run output for this run_id
    if output_path.exists():
        output_path.unlink()

    all_docs = []

    # ── 3. Dispatch collectors ─────────────────────────────────────────────────

    # ── ai_company_blogs ──────────────────────────────────────────────────────
    if "ai_company_blogs" in enabled_groups:
        blogs_window = _window_for_group(manifest, "ai_company_blogs")
        blog_caps = _collector_caps(manifest, "ai_company_blogs")
        print("[Layer 1] Collecting: official company blogs...")
        print(f"  Window: {_window_label(blogs_window)}")
        from pipelines.layer_1_extraction.official_company_blog_collector import collect as collect_blogs
        docs = collect_blogs(run_id=run_id, max_per_source=int(blog_caps.get("max_per_source", 10)),
                             output_path=output_path, layer1_dir=layer1_dir,
                             start_at=blogs_window.get("start"), end_at=blogs_window.get("end"))
        print(f"  → {len(docs)} blog posts\n")
        all_docs.extend(docs)

    # ── research_papers ───────────────────────────────────────────────────────
    if "research_papers" in enabled_groups:
        papers_window = _window_for_group(manifest, "research_papers")
        paper_caps = _collector_caps(manifest, "research_papers")
        print("[Layer 1] Collecting: research papers (arXiv)...")
        print(f"  Window: {_window_label(papers_window)}")
        from pipelines.layer_1_extraction.research_paper_collector import collect as collect_papers
        categories = query_plan.get("research_papers", {}).get("categories", ["cs.AI", "cs.LG", "cs.CL"])
        docs = collect_papers(run_id=run_id, categories=categories, max_per_category=int(paper_caps.get("max_per_category", 10)),
                              output_path=output_path, layer1_dir=layer1_dir,
                              start_at=papers_window.get("start"), end_at=papers_window.get("end"))
        print(f"  → {len(docs)} papers\n")
        all_docs.extend(docs)

    # ── tech_news_apis ────────────────────────────────────────────────────────
    if "tech_news_apis" in enabled_groups:
        news_window = _window_for_group(manifest, "tech_news_apis")
        news_caps = _collector_caps(manifest, "tech_news_apis")
        print("[Layer 1] Collecting: tech news APIs...")
        print(f"  Window: {_window_label(news_window)}")
        from pipelines.layer_1_extraction.tech_news_api_collector import collect as collect_news
        queries = query_plan.get("tech_news_apis", [])
        primary_query = queries[0] if queries else "artificial intelligence OR LLM"
        news_days_back = window_days_for_fetch(news_window)
        docs = collect_news(run_id=run_id, query=primary_query, max_per_source=int(news_caps.get("max_per_source", 10)),
                            output_path=output_path, layer1_dir=layer1_dir,
                            days_back=news_days_back,
                            start_at=news_window.get("start"), end_at=news_window.get("end"))
        print(f"  → {len(docs)} news articles\n")
        all_docs.extend(docs)

    # ── community_signals ─────────────────────────────────────────────────────
    if "community_signals" in enabled_groups:
        community_window = _window_for_group(manifest, "community_signals")
        community_caps = _collector_caps(manifest, "community_signals")
        print("[Layer 1] Collecting: community signals (Hacker News)...")
        print(f"  Window: {_window_label(community_window)}")
        from pipelines.layer_1_extraction.community_signal_collector import collect as collect_community
        docs = collect_community(run_id=run_id, story_type="top", max_stories=int(community_caps.get("max_stories", 20)),
                                 output_path=output_path, layer1_dir=layer1_dir,
                                 start_at=community_window.get("start"), end_at=community_window.get("end"))
        print(f"  → {len(docs)} HN stories\n")
        all_docs.extend(docs)

    # ── github_open_source_signals ────────────────────────────────────────────
    if "github_open_source_signals" in enabled_groups:
        github_window = _window_for_group(manifest, "github_open_source_signals")
        github_caps = _collector_caps(manifest, "github_open_source_signals")
        print("[Layer 1] Collecting: GitHub open-source signals...")
        print(f"  Window: {_window_label(github_window)}")
        from pipelines.layer_1_extraction.github_open_source_collector import collect as collect_github
        topics = query_plan.get("github_open_source_signals", {}).get("topics", [])
        queries = [" ".join(topics[:3])] if topics else ["artificial intelligence LLM"]
        github_days_back = window_days_for_fetch(github_window) or 7
        docs = collect_github(run_id=run_id, queries=queries, max_per_query=int(github_caps.get("max_per_query", 5)),
                              days_back=github_days_back,
                              output_path=output_path, layer1_dir=layer1_dir,
                              start_at=github_window.get("start"), end_at=github_window.get("end"))
        print(f"  → {len(docs)} repos\n")
        all_docs.extend(docs)

    # ── youtube_podcast_transcripts ───────────────────────────────────────────
    if "youtube_podcast_transcripts" in enabled_groups and not skip_youtube:
        youtube_window = _window_for_group(manifest, "youtube_podcast_transcripts")
        print("[Layer 1] Collecting: YouTube (requires YOUTUBE_API_KEY)...")
        print(f"  Window: {_window_label(youtube_window)}")
        from pipelines.layer_1_extraction.youtube_podcast_collector import collect_from_config as collect_youtube
        youtube_plan = query_plan.get("youtube_podcast_transcripts", {})
        youtube_days_back = window_days_for_fetch(youtube_window) or 7
        docs = collect_youtube(
            run_id=run_id,
            manifest=manifest,
            days_back=youtube_days_back,
            output_path=output_path,
            layer1_dir=layer1_dir,
            start_at=youtube_window.get("start"),
            end_at=youtube_window.get("end"),
            default_search_query=youtube_plan.get("search_query"),
        )
        print(f"  → {len(docs)} YouTube transcript(s)\n")
        all_docs.extend(docs)

    # ── 4. Package ────────────────────────────────────────────────────────────
    print(f"[Layer 1] Total collected: {len(all_docs)} documents")
    print("[Layer 1] Building extraction manifest...")
    extraction_manifest = build_extraction_manifest(run_id=run_id, layer1_dir=layer1_dir)

    # ── 5. Validate ───────────────────────────────────────────────────────────
    print("[Layer 1] Validating output...")
    report = validate(run_id=run_id, layer1_dir=layer1_dir)
    write_report(run_id=run_id, report=report, layer1_dir=layer1_dir)

    finished_at = datetime.now(timezone.utc)
    elapsed = (finished_at - started_at).total_seconds()

    print(f"\n{'='*55}")
    print(f"Layer 1 {'PASSED' if report['passed'] else 'FAILED'}")
    print(f"  Documents    : {len(all_docs)}")
    print(f"  Source groups: {extraction_manifest['totals']['source_groups_collected']}")
    print(f"  Failed events: {extraction_manifest['totals']['failed_source_events']}")
    print(f"  Elapsed      : {elapsed:.1f}s")
    print(f"  Output       : {layer1_dir}")
    if not report["passed"]:
        print(f"  Failure      : {report['failure_reason']}")
    print(f"{'='*55}\n")

    return extraction_manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Layer 1 — Source Extraction Orchestrator")
    parser.add_argument("--run-id",   required=False, help="Run ID from Layer 0")
    parser.add_argument("--manifest", required=False, help="Direct path to run_manifest.json")
    parser.add_argument("--skip-youtube", action="store_true",
                        help="Skip YouTube collection (no API key / quota)")
    args = parser.parse_args()

    if args.manifest:
        manifest_path = Path(args.manifest)
        run_id = json.loads(manifest_path.read_text()).get("run_id", "unknown")
    elif args.run_id:
        run_id = args.run_id
        manifest_path = None
    else:
        # Auto-discover: use most recently created run manifest
        run_dirs = sorted(RUNS_DIR.glob("*/run_manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not run_dirs:
            print("No run manifests found. Run run_layer_0.py first.")
            sys.exit(1)
        manifest_path = run_dirs[0]
        run_id = json.loads(manifest_path.read_text()).get("run_id", "unknown")
        print(f"Auto-discovered manifest: {manifest_path}")

    result = run_layer_1(run_id=run_id, manifest_path=manifest_path, skip_youtube=args.skip_youtube)
    print(f"Layer 2 input: {result['layer_2_handoff']['input_file']}")
    print(f"Documents ready: {result['layer_2_handoff']['doc_count']}")
