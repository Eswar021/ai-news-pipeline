"""
Layer 3 — Module 4: Entity + Topic Mapper

Extracts entities (companies, models, products, people) and topics
from each document using keyword/alias dictionary matching.

Matching is done against:
  - document title (higher confidence)
  - first 500 chars of clean text if available

Config: config/entity_topic_taxonomy.yaml

Usage:
    python entity_topic_mapper.py --run-id run_2026_05_10_48h_auto
"""

import re
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

_TAXONOMY_PATH = Path(__file__).resolve().parents[2] / "config" / "entity_topic_taxonomy.yaml"


def _load_taxonomy() -> dict:
    if _HAS_YAML:
        with open(_TAXONOMY_PATH) as f:
            return yaml.safe_load(f)
    import json as _json
    raise RuntimeError("PyYAML not installed — run: pip install pyyaml")


def _make_pattern(terms: list[str]) -> re.Pattern:
    escaped = sorted([re.escape(t) for t in terms], key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(escaped) + r")\b", re.IGNORECASE)


def _build_matchers(taxonomy: dict) -> dict:
    """
    Pre-compile regex patterns for all entity/topic categories.
    Returns a nested dict: {category: {name: pattern, ...}} for entities,
    and {topic_id: pattern} for topics.
    """
    matchers = {"entities": {}, "topics": {}}

    for entity_type, entries in taxonomy.get("entities", {}).items():
        matchers["entities"][entity_type] = {}
        for entry in entries:
            name = entry["name"]
            aliases = entry.get("aliases", [])
            all_terms = [name] + aliases
            matchers["entities"][entity_type][name] = _make_pattern(all_terms)

    for topic_id, topic_cfg in taxonomy.get("topics", {}).items():
        keywords = topic_cfg.get("keywords", [])
        if keywords:
            matchers["topics"][topic_id] = {
                "label": topic_cfg.get("label", topic_id),
                "pattern": _make_pattern(keywords),
            }

    return matchers


# Global singleton loaded once
_taxonomy = _load_taxonomy()
_matchers = _build_matchers(_taxonomy)


def map_entities_and_topics(doc: dict, clean_text_snippet: str = "") -> dict:
    """
    Extract entities and topics from a document.

    Args:
        doc: canonical document dict
        clean_text_snippet: first ~500 chars of clean text (optional)

    Returns:
        {
            "canonical_document_id": str,
            "entities": {"companies": [...], "models": [...], "products": [...], "people": [...]},
            "topics":   [{"topic_id": str, "label": str, "confidence": float}, ...],
            "primary_entities": [str],  # top-level company/product keys for clustering
        }
    """
    title = (doc.get("title") or "").strip()
    search_text = f"{title} {clean_text_snippet}"[:600]

    entities: dict[str, list[str]] = {
        "companies": [], "models": [], "products": [], "people": []
    }
    for entity_type, name_patterns in _matchers["entities"].items():
        for name, pattern in name_patterns.items():
            if pattern.search(search_text):
                if name not in entities[entity_type]:
                    entities[entity_type].append(name)

    topics: list[dict] = []
    for topic_id, tc in _matchers["topics"].items():
        if tc["pattern"].search(search_text):
            confidence = 0.85 if tc["pattern"].search(title) else 0.65
            topics.append({"topic_id": topic_id, "label": tc["label"], "confidence": confidence})
    topics.sort(key=lambda t: -t["confidence"])

    # Primary entities — for clustering overlap checks
    primary_entities = (
        entities["companies"]
        + entities["models"]
        + entities["products"]
    )

    return {
        "canonical_document_id": doc["canonical_document_id"],
        "entities":              entities,
        "topics":                topics,
        "primary_entities":      primary_entities,
    }


def map_all(docs: list[dict], layer2_dir: Path = None) -> list[dict]:
    """Map entities and topics for all documents."""
    results = []
    for doc in docs:
        snippet = ""
        if layer2_dir and doc.get("clean_text_path"):
            txt_path = Path(doc["clean_text_path"])
            if txt_path.exists():
                try:
                    snippet = txt_path.read_text(encoding="utf-8")[:500]
                except Exception:
                    pass
        results.append(map_entities_and_topics(doc, snippet))
    return results


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=False)
    args = parser.parse_args()

    run_id = args.run_id
    if not run_id:
        for rp in sorted(RUNS_DIR.glob("*/run_manifest.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True):
            if (rp.parent / "layer_2" / "canonical_documents.jsonl").exists():
                run_id = rp.parent.name
                break
        print(f"Auto-discovered run: {run_id}")

    layer2_dir = RUNS_DIR / run_id / "layer_2"
    docs = [json.loads(l) for l in (layer2_dir / "canonical_documents.jsonl")
            .read_text().splitlines() if l.strip()]

    results = map_all(docs, layer2_dir)

    print(f"\nEntity + Topic Mapper — {run_id}")
    print(f"  Processed: {len(results)} docs")

    # Summary: how many docs have each entity type
    from collections import Counter
    company_hits = Counter()
    topic_hits = Counter()
    for r in results:
        for c in r["entities"]["companies"]:
            company_hits[c] += 1
        for t in r["topics"]:
            topic_hits[t["label"]] += 1

    print("\n  Top companies mentioned:")
    for c, n in company_hits.most_common(10):
        print(f"    {c}: {n}")
    print("\n  Top topics:")
    for t, n in topic_hits.most_common(10):
        print(f"    {t}: {n}")

    # Show a few samples
    print("\n  Sample mappings:")
    for r in results[:5]:
        doc = next(d for d in docs if d["canonical_document_id"] == r["canonical_document_id"])
        print(f"  [{doc['source_group'][:12]}] {doc['title'][:55]}")
        print(f"    companies={r['entities']['companies']}")
        print(f"    models={r['entities']['models']}")
        print(f"    topics={[t['label'] for t in r['topics'][:3]]}")
