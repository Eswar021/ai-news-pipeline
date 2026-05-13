"""
Layer 4 — Module 1: Story Evidence Loader

Loads Layer 3 story clusters plus Layer 2 canonical documents/source spans and
builds document-first evidence bundles for every story recommended for Layer 4.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR
from pipelines.runtime_manifest import get_layer_limits, load_manifest

_PRIMARY_ROLES = {"primary_evidence", "company_blog", "official_announcement"}
_SECONDARY_ROLES = {"secondary_evidence", "cross_reference", "industry_news", "news_coverage"}
_RESEARCH_ROLES = {"research_evidence", "research_paper", "arxiv_paper", "academic_paper"}
_TECHNICAL_ROLES = {"technical_artifact", "github_repo", "technical_doc", "code_artifact"}
_TREND_ROLES = {
    "community_signal",
    "social_mention",
    "forum_post",
    "community_discussion",
}
_SKIP_COMPLETENESS = {"title_only", "metadata_only"}

_BUCKET_PRIORITY = {
    "primary_evidence_docs": 0,
    "secondary_evidence_docs": 1,
    "research_evidence_docs": 2,
    "technical_artifact_docs": 3,
    "trend_signal_docs": 4,
}


def _classify_document(doc: dict) -> str:
    role = doc.get("source_role", "")
    tier = float(doc.get("trust_tier", 4) or 4)
    if role in _RESEARCH_ROLES:
        return "research_evidence_docs"
    if role in _TECHNICAL_ROLES:
        return "technical_artifact_docs"
    if role in _TREND_ROLES:
        return "trend_signal_docs"
    if tier <= 1.5 or role in _PRIMARY_ROLES:
        return "primary_evidence_docs"
    if tier <= 2.5 or role in _SECONDARY_ROLES:
        return "secondary_evidence_docs"
    return "trend_signal_docs"


def _load_clean_text(doc: dict, spans_for_doc: list[dict]) -> str:
    clean_text_path = doc.get("clean_text_path") or ""
    if clean_text_path:
        path = Path(clean_text_path)
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    return "\n\n".join(span.get("text", "").strip() for span in spans_for_doc if span.get("text", "").strip()).strip()


def _eligible_for_extraction(doc: dict, clean_text: str) -> bool:
    if not doc.get("usable_for_claim_extraction", False):
        return False
    if doc.get("content_completeness") in _SKIP_COMPLETENESS:
        return False
    if len(clean_text) < 80:
        return False
    return True


def _document_sort_key(entry: dict) -> tuple:
    doc = entry["document"]
    return (
        _BUCKET_PRIORITY.get(entry["bucket"], 99),
        float(doc.get("trust_tier", 4) or 4),
        -int(doc.get("word_count", 0) or 0),
        doc.get("canonical_document_id", ""),
    )


def load(run_id: str, layer3_dir: Path, layer2_dir: Path, max_stories: int | None = None) -> dict:
    manifest = load_manifest(run_id=run_id)
    layer4_limits = get_layer_limits(manifest, "layer_4")

    if max_stories is None:
        max_stories = int(layer4_limits.get("max_stories", 0))
    if max_stories <= 0:
        raise ValueError("execution_policy.layer_limits.layer_4.max_stories must be > 0")

    max_documents_per_story = int(layer4_limits.get("max_documents_per_story", 0))
    if max_documents_per_story <= 0:
        raise ValueError("execution_policy.layer_limits.layer_4.max_documents_per_story must be > 0")

    ranked_stories = json.loads((layer3_dir / "ranked_stories.json").read_text(encoding="utf-8"))["ranked_stories"]
    selected_ranked = [story for story in ranked_stories if story.get("recommended_for_layer_4")][:max_stories]
    selected_story_ids = {story["story_id"] for story in selected_ranked}

    clusters = json.loads((layer3_dir / "story_clusters.json").read_text(encoding="utf-8"))["story_clusters"]
    cluster_by_id = {cluster["story_id"]: cluster for cluster in clusters}

    docs_by_id: dict[str, dict] = {}
    for line in (layer2_dir / "canonical_documents.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            doc = json.loads(line)
            docs_by_id[doc["canonical_document_id"]] = doc

    spans_by_id: dict[str, dict] = {}
    spans_by_document_id: dict[str, list[dict]] = {}
    for line in (layer2_dir / "source_spans.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            span = json.loads(line)
            spans_by_id[span["span_id"]] = span
            spans_by_document_id.setdefault(span["canonical_document_id"], []).append(span)

    evidence_bundles: list[dict] = []
    total_spans_loaded = 0
    total_documents_considered = 0
    total_documents_selected = 0
    missing_documents = 0
    missing_spans = 0

    for ranked in selected_ranked:
        story_id = ranked["story_id"]
        cluster = cluster_by_id.get(story_id)
        if not cluster:
            continue

        member_docs: list[dict] = []
        document_entries: list[dict] = []

        for doc_id in cluster["cluster_members"].get("canonical_document_ids", []):
            doc = docs_by_id.get(doc_id)
            if not doc:
                missing_documents += 1
                continue

            spans_for_doc = sorted(
                spans_by_document_id.get(doc_id, []),
                key=lambda record: int(record.get("span_index", 0)),
            )
            if not spans_for_doc:
                missing_spans += 1

            member_docs.append(doc)
            total_documents_considered += 1
            total_spans_loaded += len(spans_for_doc)

            clean_text = _load_clean_text(doc, spans_for_doc)
            bucket = _classify_document(doc)
            document_entries.append(
                {
                    "bucket": bucket,
                    "document": doc,
                    "clean_text": clean_text,
                    "spans": spans_for_doc,
                    "eligible_for_extraction": _eligible_for_extraction(doc, clean_text),
                }
            )

        document_entries.sort(key=_document_sort_key)
        eligible_documents = [entry for entry in document_entries if entry["eligible_for_extraction"]][:max_documents_per_story]
        total_documents_selected += len(eligible_documents)

        evidence_bundles.append(
            {
                "story_id": story_id,
                "story_title": ranked["story_title"],
                "story_type": ranked["story_type"],
                "rank": ranked["rank"],
                "total_story_score": ranked["total_story_score"],
                "cluster": cluster,
                "member_docs": member_docs,
                "document_entries": document_entries,
                "eligible_documents": eligible_documents,
                "document_counts": {
                    "member_documents": len(member_docs),
                    "eligible_documents": len(eligible_documents),
                    "excluded_documents": max(len(document_entries) - len(eligible_documents), 0),
                },
                "total_spans": sum(len(entry["spans"]) for entry in document_entries),
            }
        )

    return {
        "stories_loaded": len(evidence_bundles),
        "evidence_bundles": evidence_bundles,
        "docs_by_id": docs_by_id,
        "spans_by_id": spans_by_id,
        "spans_by_document_id": spans_by_document_id,
        "counts": {
            "stories_selected": len(selected_story_ids),
            "total_spans_loaded": total_spans_loaded,
            "missing_spans": missing_spans,
            "documents_considered": total_documents_considered,
            "documents_selected": total_documents_selected,
            "missing_documents": missing_documents,
        },
    }


if __name__ == "__main__":
    run_id = None
    for manifest_path in sorted(RUNS_DIR.glob("*/run_manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True):
        if (manifest_path.parent / "layer_3" / "ranked_stories.json").exists():
            run_id = manifest_path.parent.name
            break
    print(f"Auto-discovered run: {run_id}")

    layer3_dir = RUNS_DIR / run_id / "layer_3"
    layer2_dir = RUNS_DIR / run_id / "layer_2"
    result = load(run_id, layer3_dir, layer2_dir)

    print(f"\nEvidence Loader — {run_id}")
    print(f"  Stories loaded        : {result['stories_loaded']}")
    print(f"  Documents selected    : {result['counts']['documents_selected']}")
    print(f"  Documents considered  : {result['counts']['documents_considered']}")
    print(f"  Total spans loaded    : {result['counts']['total_spans_loaded']}")
    for bundle in result["evidence_bundles"]:
        print(
            f"  [{bundle['rank']:2}] {bundle['story_title'][:45]:45s} "
            f"docs={bundle['document_counts']['eligible_documents']}/"
            f"{bundle['document_counts']['member_documents']} spans={bundle['total_spans']}"
        )
