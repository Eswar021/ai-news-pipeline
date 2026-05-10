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

from pipelines.layer_1_extraction.source_registry_loader import load_active_sources
from pipelines.layer_1_extraction.query_topic_expansion_planner import expand_queries
from pipelines.layer_1_extraction.layer1_output_packager import build_extraction_manifest
from pipelines.layer_1_extraction.layer1_validation_gate import validate, write_report
from pipelines.layer_1_extraction.extraction_audit_logger import log_event

from config.paths import SOURCES_YAML, SOURCE_STRATEGY_YAML


def _load_manifest(manifest_path: Path) -> dict:
    with open(manifest_path, encoding="utf-8") as f:
        return json.load(f)


def _enabled_groups(manifest: dict) -> list:
    """Extract enabled source group names from the run manifest."""
    scope = manifest.get("source_scope", {})
    return [g for g, info in scope.get("source_groups", {}).items()
            if info.get("enabled", False)]


def _query_themes(manifest: dict) -> list:
    """Get query themes from manifest, fall back to defaults."""
    return manifest.get("query_themes", [
        "AI agents", "LLM releases", "AI coding tools", "open-source AI", "AI research"
    ])


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
        # Fallback: load from source_strategy.yaml directly
        from pipelines.layer_1_extraction.source_registry_loader import load_active_sources
        sources = load_active_sources(SOURCES_YAML, SOURCE_STRATEGY_YAML)
        enabled_groups = list({s["source_group"] for s in sources})

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
        print("[Layer 1] Collecting: official company blogs...")
        from pipelines.layer_1_extraction.official_company_blog_collector import collect as collect_blogs
        docs = collect_blogs(run_id=run_id, max_per_source=10,
                             output_path=output_path, layer1_dir=layer1_dir)
        print(f"  → {len(docs)} blog posts\n")
        all_docs.extend(docs)

    # ── research_papers ───────────────────────────────────────────────────────
    if "research_papers" in enabled_groups:
        print("[Layer 1] Collecting: research papers (arXiv)...")
        from pipelines.layer_1_extraction.research_paper_collector import collect as collect_papers
        categories = query_plan.get("research_papers", {}).get("categories", ["cs.AI", "cs.LG", "cs.CL"])
        docs = collect_papers(run_id=run_id, categories=categories, max_per_category=10,
                              output_path=output_path, layer1_dir=layer1_dir)
        print(f"  → {len(docs)} papers\n")
        all_docs.extend(docs)

    # ── tech_news_apis ────────────────────────────────────────────────────────
    if "tech_news_apis" in enabled_groups:
        print("[Layer 1] Collecting: tech news APIs...")
        from pipelines.layer_1_extraction.tech_news_api_collector import collect as collect_news
        queries = query_plan.get("tech_news_apis", [])
        primary_query = queries[0] if queries else "artificial intelligence OR LLM"
        docs = collect_news(run_id=run_id, query=primary_query, max_per_source=10,
                            output_path=output_path, layer1_dir=layer1_dir)
        print(f"  → {len(docs)} news articles\n")
        all_docs.extend(docs)

    # ── community_signals ─────────────────────────────────────────────────────
    if "community_signals" in enabled_groups:
        print("[Layer 1] Collecting: community signals (Hacker News)...")
        from pipelines.layer_1_extraction.community_signal_collector import collect as collect_community
        docs = collect_community(run_id=run_id, story_type="top", max_stories=20,
                                 output_path=output_path, layer1_dir=layer1_dir)
        print(f"  → {len(docs)} HN stories\n")
        all_docs.extend(docs)

    # ── github_open_source_signals ────────────────────────────────────────────
    if "github_open_source_signals" in enabled_groups:
        print("[Layer 1] Collecting: GitHub open-source signals...")
        from pipelines.layer_1_extraction.github_open_source_collector import collect as collect_github
        topics = query_plan.get("github_open_source_signals", {}).get("topics", [])
        queries = [" ".join(topics[:3])] if topics else ["artificial intelligence LLM"]
        docs = collect_github(run_id=run_id, queries=queries, max_per_query=5,
                              output_path=output_path, layer1_dir=layer1_dir)
        print(f"  → {len(docs)} repos\n")
        all_docs.extend(docs)

    # ── youtube_podcast_transcripts ───────────────────────────────────────────
    if "youtube_podcast_transcripts" in enabled_groups and not skip_youtube:
        print("[Layer 1] Collecting: YouTube (requires YOUTUBE_API_KEY)...")
        print("  [skipped — run with channel IDs via youtube_podcast_collector.py directly]\n")

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
