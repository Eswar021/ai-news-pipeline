from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import re

import numpy as np

from src.pipeline.L1_collection.common import clean_text, parse_datetime
from src.pipeline.L3_story_map.fingerprint import build_fingerprint_text
from src.pipeline.L3_story_map.signals import (
    extract_record_signals,
    story_key_overlap_stats,
    title_overlap_stats,
)


SEMANTIC_PRIMARY_THRESHOLD = 0.80
SEMANTIC_SUPPORTED_THRESHOLD = 0.78
SEMANTIC_TITLE_ANCHOR_THRESHOLD = 0.74
MAX_PAIR_HOURS = 120.0
SEMANTIC_MERGE_GROUPS = {
    "ai_company_blogs",
    "tech_news_apis",
    "youtube_podcast_transcripts",
}


@dataclass
class ClusterStats:
    exact_match_edges: int = 0
    semantic_edges: int = 0
    dropped_singletons: int = 0


def cluster_records(records: list[dict], layer3_cfg: dict | None = None) -> tuple[list[dict], dict[str, int]]:
    layer3_cfg = layer3_cfg or {}
    indexed = [_enrich_record(record, idx) for idx, record in enumerate(records)]
    uf = _UnionFind(len(indexed))
    stats = ClusterStats()
    edge_reasons: dict[tuple[int, int], str] = {}

    _apply_semantic_edges(indexed, uf, edge_reasons, stats, layer3_cfg)

    components: dict[int, list[dict]] = defaultdict(list)
    for record in indexed:
        components[uf.find(record["_idx"])].append(record)

    clusters: list[dict] = []
    for members in components.values():
        members.sort(key=_record_sort_key)
        if len(members) == 1 and not _is_storyworthy_singleton(members[0]):
            stats.dropped_singletons += 1
            continue

        component_root = uf.find(members[0]["_idx"])
        component_pairs = {
            reason
            for (left, right), reason in edge_reasons.items()
            if uf.find(left) == component_root and uf.find(right) == component_root
        }
        clusters.append(_build_cluster(members, sorted(component_pairs)))

    clusters.sort(key=lambda cluster: cluster["time_range"]["first_seen_at"] or "", reverse=True)
    return clusters, {
        "exact_match_edges": stats.exact_match_edges,
        "semantic_edges": stats.semantic_edges,
        "dropped_singletons": stats.dropped_singletons,
    }


def _apply_semantic_edges(
    records: list[dict],
    uf: "_UnionFind",
    edge_reasons: dict[tuple[int, int], str],
    stats: ClusterStats,
    layer3_cfg: dict,
) -> None:
    if len(records) < 2:
        return

    fingerprints = [record["_fingerprint_text"] for record in records]
    vectors = _embed_texts(fingerprints, model_name=layer3_cfg.get("embedding_model", "all-MiniLM-L6-v2"))

    for left_index, left in enumerate(records):
        for right_index in range(left_index + 1, len(records)):
            right = records[right_index]
            if _hours_apart(left.get("published_at", ""), right.get("published_at", "")) > MAX_PAIR_HOURS:
                continue

            similarity = _cosine_similarity(vectors[left_index], vectors[right_index])
            reason = _same_story_reason(left, right, similarity)
            if not reason:
                continue

            if uf.union(left["_idx"], right["_idx"]):
                stats.semantic_edges += 1
            edge_reasons[_edge_key(left["_idx"], right["_idx"])] = reason


def _same_story_reason(left: dict, right: dict, similarity: float) -> str | None:
    if similarity < SEMANTIC_TITLE_ANCHOR_THRESHOLD:
        return None
    if not _semantic_pair_allowed(left, right):
        return None

    title_overlap, title_jaccard = title_overlap_stats(left, right)
    story_overlap, _story_jaccard, anchor_overlap = story_key_overlap_stats(left, right)

    if (
        similarity >= SEMANTIC_PRIMARY_THRESHOLD
        and title_overlap >= 4
        and title_jaccard >= 0.30
    ):
        return "semantic_title_match"

    if (
        similarity >= SEMANTIC_TITLE_ANCHOR_THRESHOLD
        and title_overlap >= 4
        and title_jaccard >= 0.34
        and story_overlap >= 4
        and anchor_overlap >= 1
    ):
        return "semantic_title_anchor_match"

    if (
        similarity >= SEMANTIC_SUPPORTED_THRESHOLD
        and title_overlap >= 3
        and title_jaccard >= 0.25
        and story_overlap >= 4
        and anchor_overlap >= 1
    ):
        return "semantic_supported_match"

    if (
        similarity >= 0.86
        and title_overlap >= 3
        and title_jaccard >= 0.22
        and anchor_overlap >= 1
    ):
        return "semantic_high_match"

    return None


def _semantic_pair_allowed(left: dict, right: dict) -> bool:
    groups = {left.get("source_group", ""), right.get("source_group", "")}
    if not groups <= SEMANTIC_MERGE_GROUPS:
        return False

    # L2 owns duplicate removal. L3 should only merge clear same-story coverage.
    if "youtube_podcast_transcripts" in groups and len(groups) == 1:
        return False

    return True


def _embed_texts(texts: list[str], *, model_name: str) -> np.ndarray:
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:  # pragma: no cover - import failure is explicit
        raise RuntimeError(
            "sentence-transformers is required for L3 semantic clustering."
        ) from exc

    try:
        model = SentenceTransformer(model_name)
    except Exception as exc:  # pragma: no cover - runtime environment dependent
        raise RuntimeError(
            f"Could not load embedding model '{model_name}'. "
            "Ensure sentence-transformers is installed and the model can be downloaded or is already cached."
        ) from exc

    return np.asarray(model.encode(texts, show_progress_bar=False, normalize_embeddings=True))


def _build_cluster(members: list[dict], match_reasons: list[str]) -> dict:
    first_seen = min((record.get("published_at", "") for record in members if record.get("published_at")), default="")
    last_seen = max((record.get("published_at", "") for record in members if record.get("published_at")), default="")
    source_groups = sorted({record.get("source_group", "") for record in members if record.get("source_group")})
    story_signals = {
        "official_record_count": sum(1 for record in members if record.get("source_group") == "ai_company_blogs"),
        "news_record_count": sum(1 for record in members if record.get("source_group") == "tech_news_apis"),
        "research_record_count": sum(1 for record in members if record.get("source_group") == "research_papers"),
        "youtube_record_count": sum(1 for record in members if record.get("source_group") == "youtube_podcast_transcripts"),
        "community_record_count": sum(1 for record in members if record.get("source_group") == "community_signals"),
        "provider_counts": dict(Counter(record["_source_label"] for record in members)),
        "event_type_counts": dict(Counter(record["_event_type_hint"] for record in members)),
        "organization_counts": dict(Counter(org for record in members for org in record["_org_hints"])),
        "product_counts": dict(Counter(product for record in members for product in record["_product_hints"])),
        "action_counts": dict(Counter(action for record in members for action in record["_action_hints"])),
    }
    return {
        "story_id": _build_story_id(members),
        "story_title": _pick_story_title(members),
        "story_type_hint": _infer_story_type(members),
        "story_identity": {},
        "record_count": len(members),
        "source_groups": source_groups,
        "time_range": {
            "first_seen_at": first_seen,
            "last_seen_at": last_seen,
        },
        "match_reasons": match_reasons,
        "story_signals": story_signals,
        "records": [_strip_internal_fields(record) for record in members],
    }


def _pick_story_title(records: list[dict]) -> str:
    ordered = sorted(records, key=lambda record: (-_record_strength(record), _record_sort_key(record)))
    return ordered[0].get("title", "") if ordered else ""


def _infer_story_type(records: list[dict]) -> str:
    groups = Counter(record.get("source_group", "") for record in records)
    events = Counter(record["_event_type_hint"] for record in records if record["_event_type_hint"] != "unknown")
    if events:
        top_event, _ = events.most_common(1)[0]
        if top_event == "product_update" and groups["ai_company_blogs"]:
            return "official_update"
        if top_event == "product_update":
            return "industry_news"
        if top_event == "research_paper":
            return "research_result"
        if top_event == "community_tooling":
            return "community_repository"
        return top_event
    if groups == Counter({"research_papers": len(records)}):
        return "research_result"
    if groups["tech_news_apis"] >= max(groups.values(), default=0):
        return "industry_news"
    return "mixed_story"


def _record_strength(record: dict) -> int:
    group = record.get("source_group", "")
    score = {
        "ai_company_blogs": 5,
        "tech_news_apis": 4,
        "community_signals": 3,
        "research_papers": 2,
        "youtube_podcast_transcripts": 1,
    }.get(group, 0)
    score += int(record.get("trust_tier", 4) == 1)
    score += int(record.get("stars", 0) > 5000)
    score += int(record.get("score", 0) > 100)
    return score


def _record_sort_key(record: dict) -> tuple[str, str]:
    return (record.get("published_at", ""), record.get("title", ""))


def _is_storyworthy_singleton(record: dict) -> bool:
    group = record.get("source_group", "")
    content = clean_text(record.get("content", ""))
    if group == "ai_company_blogs":
        return True
    if group == "tech_news_apis":
        return len(content) >= 300
    if group == "research_papers":
        return True
    if group == "youtube_podcast_transcripts":
        return len(content) >= 800
    if group == "community_signals":
        if record.get("provider") == "github":
            return int(record.get("stars", 0)) >= 100
        return int(record.get("score", 0)) >= 30 or int(record.get("comment_count", 0)) >= 15
    return False


def _enrich_record(record: dict, idx: int) -> dict:
    enriched = dict(record)
    enriched["_idx"] = idx
    enriched["_fingerprint_text"] = build_fingerprint_text(record)
    signals = extract_record_signals(record)
    enriched["_source_label"] = signals["source_label"]
    enriched["_org_hints"] = signals["org_hints"]
    enriched["_product_hints"] = signals["product_hints"]
    enriched["_action_hints"] = signals["action_hints"]
    enriched["_event_type_hint"] = signals["event_type_hint"]
    enriched["_title_overlap_tokens"] = signals["title_overlap_tokens"]
    enriched["_story_key_tokens"] = signals["story_key_tokens"]
    enriched["_anchor_story_tokens"] = signals["anchor_story_tokens"]
    return enriched


def _strip_internal_fields(record: dict) -> dict:
    return {
        key: value
        for key, value in record.items()
        if not key.startswith("_")
    }


def _build_story_id(records: list[dict]) -> str:
    title = _pick_story_title(records).lower()[:40]
    slug = re.sub(r"[^a-z0-9]+", "_", title).strip("_") or "story"
    first = min((record.get("published_at", "") for record in records if record.get("published_at")), default="0000-00-00")
    date_part = first[:10].replace("-", "")
    base = "|".join(
        sorted(
            clean_text(record.get("record_key", ""))
            or clean_text(record.get("url", ""))
            or clean_text(record.get("title", ""))
            for record in records
        )
    )
    suffix = hashlib.sha1(base.encode("utf-8")).hexdigest()[:6]
    return f"story_{date_part}_{slug}_{suffix}"


def _hours_apart(left: str, right: str) -> float:
    left_dt = parse_datetime(left)
    right_dt = parse_datetime(right)
    if left_dt is None or right_dt is None:
        return 9999.0
    return abs((left_dt - right_dt).total_seconds()) / 3600.0


def _cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    if left.size == 0 or right.size == 0:
        return 0.0
    return float(np.dot(left, right) / (np.linalg.norm(left) * np.linalg.norm(right)))


def _edge_key(left: int, right: int) -> tuple[int, int]:
    return (left, right) if left < right else (right, left)


class _UnionFind:
    def __init__(self, size: int):
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, item: int) -> int:
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, left: int, right: int) -> bool:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left == root_right:
            return False
        if self.rank[root_left] < self.rank[root_right]:
            self.parent[root_left] = root_right
        elif self.rank[root_left] > self.rank[root_right]:
            self.parent[root_right] = root_left
        else:
            self.parent[root_right] = root_left
            self.rank[root_left] += 1
        return True
