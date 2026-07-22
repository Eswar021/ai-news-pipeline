from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import re
from typing import Any, Callable

import numpy as np

from .fingerprint import build_fingerprint_chunks, build_fingerprint_text
from .signals import (
    extract_record_signals,
    story_key_overlap_stats,
    title_overlap_stats,
)
from .utils import clean_text, hours_between, time_span_hours


EmbeddingFn = Callable[[list[str], str], np.ndarray]
PairAdjudicator = Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
ClusterReconciler = Callable[
    [list[dict[str, Any]]],
    dict[str, list[list[str]]],
]
RecordSemanticEnricher = Callable[
    [list[dict[str, Any]]],
    list[dict[str, Any]],
]


@dataclass
class ClusterStats:
    exact_match_edges: int = 0
    semantic_edges: int = 0
    candidate_pairs: int = 0
    adjudicated_pairs: int = 0
    truncated_candidate_pairs: int = 0
    time_eligible_pairs: int = 0
    top_neighbor_pairs: int = 0
    triage_key_pairs: int = 0
    similarity_floor_pairs: int = 0
    candidate_covered_records: int = 0
    transitive_merge_rejections: int = 0
    reconciliation_components: int = 0
    reconciled_groups: int = 0
    reconciliation_splits: int = 0


def cluster_records(
    records: list[dict],
    cluster_cfg: dict,
    *,
    embedder: EmbeddingFn | None = None,
    pair_adjudicator: PairAdjudicator | None = None,
    cluster_reconciler: ClusterReconciler | None = None,
    record_semantic_enricher: RecordSemanticEnricher | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    indexed = [
        _enrich_record(
            record,
            idx,
            fingerprint_chunk_chars=int(cluster_cfg.get("fingerprint_chunk_chars", 1_800)),
            max_fingerprint_chunks=int(
                cluster_cfg.get("max_fingerprint_chunks_per_record", 128)
            ),
        )
        for idx, record in enumerate(records)
    ]
    uf = _UnionFind(len(indexed))
    stats = ClusterStats()
    edge_reasons: dict[tuple[int, int], str] = {}

    pair_decisions = _apply_semantic_edges(
        indexed,
        uf,
        edge_reasons,
        stats,
        cluster_cfg,
        embedder=embedder,
        pair_adjudicator=pair_adjudicator,
        cluster_reconciler=cluster_reconciler,
        record_semantic_enricher=record_semantic_enricher,
    )

    components: dict[int, list[dict]] = defaultdict(list)
    for record in indexed:
        components[uf.find(record["_idx"])].append(record)

    clusters: list[dict] = []
    for members in components.values():
        members.sort(key=_record_sort_key)
        component_root = uf.find(members[0]["_idx"])
        component_pairs = {
            reason
            for (left, right), reason in edge_reasons.items()
            if uf.find(left) == component_root and uf.find(right) == component_root
        }
        clusters.append(_build_cluster(members, sorted(component_pairs)))

    _attach_related_story_edges(clusters, pair_decisions)

    clusters.sort(key=lambda cluster: cluster["time_range"]["first_seen_at"] or "", reverse=True)
    return clusters, {
        "exact_match_edges": stats.exact_match_edges,
        "semantic_edges": stats.semantic_edges,
        "candidate_pair_count": stats.candidate_pairs,
        "adjudicated_pair_count": stats.adjudicated_pairs,
        "truncated_candidate_pair_count": stats.truncated_candidate_pairs,
        "time_eligible_pair_count": stats.time_eligible_pairs,
        "top_neighbor_pair_count": stats.top_neighbor_pairs,
        "triage_key_pair_count": stats.triage_key_pairs,
        "similarity_floor_pair_count": stats.similarity_floor_pairs,
        "candidate_covered_record_count": stats.candidate_covered_records,
        "transitive_merge_rejection_count": stats.transitive_merge_rejections,
        "reconciliation_component_count": stats.reconciliation_components,
        "reconciled_group_count": stats.reconciled_groups,
        "reconciliation_split_count": stats.reconciliation_splits,
        "pair_relationship_counts": dict(
            Counter(item.get("relationship", "unknown") for item in pair_decisions)
        ),
    }


def enrich_record_for_tests(record: dict, idx: int = 0) -> dict:
    return _enrich_record(record, idx)


def _apply_semantic_edges(
    records: list[dict],
    uf: "_UnionFind",
    edge_reasons: dict[tuple[int, int], str],
    stats: ClusterStats,
    cluster_cfg: dict,
    *,
    embedder: EmbeddingFn | None,
    pair_adjudicator: PairAdjudicator | None,
    cluster_reconciler: ClusterReconciler | None,
    record_semantic_enricher: RecordSemanticEnricher | None,
) -> list[dict[str, Any]]:
    if len(records) < 2:
        return []

    record_vectors = _record_chunk_vectors(
        records,
        embedding_model=cluster_cfg["embedding_model"],
        embedder=embedder or _embed_texts,
    )
    max_pair_hours = float(cluster_cfg["effective_max_pair_hours"])

    eligible_pairs: dict[tuple[int, int], float] = {}
    neighbors: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for left_index, left in enumerate(records):
        for right_index in range(left_index + 1, len(records)):
            right = records[right_index]
            if hours_between(left.get("published_at", ""), right.get("published_at", "")) > max_pair_hours:
                continue

            similarity = _record_similarity(
                record_vectors[left_index], record_vectors[right_index]
            )
            pair_key = (left_index, right_index)
            eligible_pairs[pair_key] = similarity
            neighbors[left_index].append((similarity, right_index))
            neighbors[right_index].append((similarity, left_index))

    stats.time_eligible_pairs = len(eligible_pairs)
    neighbor_limit = int(cluster_cfg.get("candidate_neighbors_per_record", 4))
    nominated: dict[tuple[int, int], set[str]] = defaultdict(set)
    for record_index, options in neighbors.items():
        for _similarity, other_index in sorted(options, key=lambda item: (-item[0], item[1]))[:neighbor_limit]:
            nominated[_edge_key(record_index, other_index)].add("top_neighbor")

    for pair_key in eligible_pairs:
        left, right = records[pair_key[0]], records[pair_key[1]]
        if eligible_pairs[pair_key] >= float(
            cluster_cfg.get("candidate_similarity_floor", 0.58)
        ):
            nominated[pair_key].add("similarity_floor")
        if _triage_story_key_overlap(left, right):
            nominated[pair_key].add("shared_triage_story_key")

    stats.top_neighbor_pairs = sum("top_neighbor" in reasons for reasons in nominated.values())
    stats.triage_key_pairs = sum("shared_triage_story_key" in reasons for reasons in nominated.values())
    stats.similarity_floor_pairs = sum("similarity_floor" in reasons for reasons in nominated.values())
    stats.candidate_covered_records = len({index for pair in nominated for index in pair})
    if record_semantic_enricher is not None and nominated:
        candidate_record_indices = sorted({index for pair in nominated for index in pair})
        candidate_records = [
            _strip_internal_fields(records[index])
            for index in candidate_record_indices
        ]
        enriched_records = record_semantic_enricher(candidate_records)
        _apply_record_semantic_enrichment(
            records,
            candidate_record_indices=candidate_record_indices,
            original_records=candidate_records,
            enriched_records=enriched_records,
        )
    candidates = [
        _pair_candidate(
            records[left_index],
            records[right_index],
            eligible_pairs[(left_index, right_index)],
            nomination_reasons=sorted(reasons),
        )
        for (left_index, right_index), reasons in nominated.items()
    ]

    candidates.sort(key=lambda item: (-item["similarity"], item["pair_id"]))
    stats.candidate_pairs = len(candidates)
    max_candidates = int(cluster_cfg.get("max_candidate_pairs", len(candidates) or 1))
    if len(candidates) > max_candidates:
        raise ValueError(
            "Story-mapping candidate nomination exceeds clustering.max_candidate_pairs; "
            "no semantic candidates were truncated. "
            f"candidate_count={len(candidates)}, configured_limit={max_candidates}"
        )

    if pair_adjudicator is not None and candidates:
        decisions = pair_adjudicator([_strip_pair_internals(item) for item in candidates])
        by_pair = {item["pair_id"]: item for item in decisions}
        stats.adjudicated_pairs = len(decisions)
    else:
        by_pair = {
            item["pair_id"]: {
                "pair_id": item["pair_id"],
                "relationship": "uncertain",
                "confidence": 0.0,
                "reason": "Semantic pair adjudication is disabled; records remain separate.",
                "decision_source": "unadjudicated",
            }
            for item in candidates
        }

    resolved: list[dict[str, Any]] = []
    decisions_by_record_pair: dict[tuple[int, int], str] = {}
    for candidate in candidates:
        decision = by_pair.get(candidate["pair_id"])
        if decision is None:
            decision = {
                "pair_id": candidate["pair_id"],
                "relationship": "uncertain",
                "confidence": 0.0,
                "reason": "Pair adjudicator omitted this candidate.",
                "decision_source": "unresolved",
            }
        resolved_item = {
            **decision,
            "left_record_key": candidate["left_record"]["record_key"],
            "right_record_key": candidate["right_record"]["record_key"],
            "similarity": candidate["similarity"],
        }
        resolved.append(resolved_item)
        decisions_by_record_pair[_edge_key(candidate["_left_index"], candidate["_right_index"])] = clean_text(
            decision.get("relationship")
        )

    if cluster_reconciler is not None:
        _apply_reconciled_semantic_edges(
            records=records,
            candidates=candidates,
            resolved=resolved,
            uf=uf,
            edge_reasons=edge_reasons,
            stats=stats,
            cluster_reconciler=cluster_reconciler,
        )
        return resolved

    for candidate in candidates:
        decision = by_pair.get(candidate["pair_id"]) or {}
        if decision.get("relationship") != "same_event":
            continue
        left = records[candidate["_left_index"]]
        right = records[candidate["_right_index"]]
        left_members = [item for item in records if uf.find(item["_idx"]) == uf.find(left["_idx"])]
        right_members = [item for item in records if uf.find(item["_idx"]) == uf.find(right["_idx"])]
        explicit_cross_decisions = [
            decisions_by_record_pair.get(
                _edge_key(left_member["_idx"], right_member["_idx"])
            )
            for left_member in left_members
            for right_member in right_members
        ]
        if any(
            relationship in {"follow_up", "broader_story_arc", "unrelated"}
            for relationship in explicit_cross_decisions
        ):
            stats.transitive_merge_rejections += 1
            continue
        if uf.union(left["_idx"], right["_idx"]):
            stats.semantic_edges += 1
        edge_reasons[_edge_key(left["_idx"], right["_idx"])] = "llm_same_event"
    return resolved


def _apply_record_semantic_enrichment(
    records: list[dict[str, Any]],
    *,
    candidate_record_indices: list[int],
    original_records: list[dict[str, Any]],
    enriched_records: list[dict[str, Any]],
) -> None:
    if len(enriched_records) != len(original_records):
        raise ValueError(
            "story-mapping semantic record enrichment returned the wrong record count"
        )
    expected_keys = [clean_text(record.get("record_key")) for record in original_records]
    returned_keys = [clean_text(record.get("record_key")) for record in enriched_records]
    if returned_keys != expected_keys:
        raise ValueError(
            "story-mapping semantic record enrichment changed record identity or order; "
            f"expected={expected_keys}, returned={returned_keys}"
        )
    for index, enriched in zip(
        candidate_record_indices,
        enriched_records,
        strict=True,
    ):
        records[index].update(enriched)


def _apply_reconciled_semantic_edges(
    *,
    records: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    resolved: list[dict[str, Any]],
    uf: "_UnionFind",
    edge_reasons: dict[tuple[int, int], str],
    stats: ClusterStats,
    cluster_reconciler: ClusterReconciler,
) -> None:
    decision_by_pair = {
        clean_text(item.get("pair_id")): item
        for item in resolved
    }
    proposal = _UnionFind(len(records))
    for candidate in candidates:
        decision = decision_by_pair.get(clean_text(candidate.get("pair_id"))) or {}
        if clean_text(decision.get("relationship")) == "same_event":
            proposal.union(candidate["_left_index"], candidate["_right_index"])

    proposed_members: dict[int, list[int]] = defaultdict(list)
    for record_index in range(len(records)):
        proposed_members[proposal.find(record_index)].append(record_index)

    components: list[dict[str, Any]] = []
    component_indices: dict[str, list[int]] = {}
    for member_indices in proposed_members.values():
        if len(member_indices) < 2:
            continue
        member_indices = sorted(member_indices)
        member_set = set(member_indices)
        record_keys = [
            clean_text(records[index].get("record_key")) or f"index_{index}"
            for index in member_indices
        ]
        component_hash = hashlib.sha1(
            "|".join(sorted(record_keys)).encode("utf-8")
        ).hexdigest()[:12]
        component_id = f"component_{component_hash}"
        component_indices[component_id] = member_indices
        components.append(
            {
                "component_id": component_id,
                "record_keys": record_keys,
                "context_mode": "event_identity_capsules_from_complete_records",
                "records": [
                    _reconciliation_record_context(records[index])
                    for index in member_indices
                ],
                "pair_decisions": [
                    {
                        **decision,
                        "left_record_key": clean_text(
                            candidate["left_record"].get("record_key")
                        ),
                        "right_record_key": clean_text(
                            candidate["right_record"].get("record_key")
                        ),
                    }
                    for candidate, decision in zip(candidates, resolved, strict=True)
                    if candidate["_left_index"] in member_set
                    and candidate["_right_index"] in member_set
                ],
            }
        )

    if not components:
        return

    stats.reconciliation_components = len(components)
    reconciled = cluster_reconciler(components)
    expected_component_ids = set(component_indices)
    returned_component_ids = set(reconciled)
    if returned_component_ids != expected_component_ids:
        raise ValueError(
            "cluster reconciler component coverage mismatch; "
            f"missing={sorted(expected_component_ids - returned_component_ids)}, "
            f"unknown={sorted(returned_component_ids - expected_component_ids)}"
        )

    record_index_by_key = {
        clean_text(record.get("record_key")) or f"index_{index}": index
        for index, record in enumerate(records)
    }
    for component in components:
        component_id = component["component_id"]
        groups = reconciled[component_id]
        expected_keys = set(component["record_keys"])
        returned_keys = [key for group in groups for key in group]
        if len(returned_keys) != len(set(returned_keys)) or set(returned_keys) != expected_keys:
            returned = set(returned_keys)
            raise ValueError(
                "cluster reconciler record coverage mismatch; "
                f"component_id={component_id}, missing={sorted(expected_keys - returned)}, "
                f"unknown={sorted(returned - expected_keys)}"
            )
        stats.reconciled_groups += len(groups)
        if len(groups) > 1:
            stats.reconciliation_splits += 1

        group_by_record = {
            record_key: group_index
            for group_index, group in enumerate(groups)
            for record_key in group
        }
        for candidate, decision in zip(candidates, resolved, strict=True):
            if clean_text(decision.get("relationship")) != "same_event":
                continue
            left_key = clean_text(candidate["left_record"].get("record_key"))
            right_key = clean_text(candidate["right_record"].get("record_key"))
            if left_key in group_by_record and right_key in group_by_record:
                if group_by_record[left_key] != group_by_record[right_key]:
                    stats.transitive_merge_rejections += 1

        for group in groups:
            if len(group) < 2:
                continue
            anchor_index = record_index_by_key[group[0]]
            for record_key in group[1:]:
                other_index = record_index_by_key[record_key]
                if uf.union(anchor_index, other_index):
                    stats.semantic_edges += 1
                edge_reasons[_edge_key(anchor_index, other_index)] = (
                    "llm_cluster_reconciled"
                )


def _reconciliation_record_context(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_key": clean_text(record.get("record_key")),
        "title": clean_text(record.get("title")),
        "url": clean_text(record.get("url")),
        "published_at": clean_text(record.get("published_at")),
        "source": clean_text(record.get("source")),
        "source_group": clean_text(record.get("source_group")),
        "source_relationship": clean_text(record.get("source_relationship")),
        "event_identity": dict(record.get("story_mapping_event_identity") or {}),
        "triage_story_keys": list(
            (record.get("editorial_triage") or {}).get("possible_story_keys") or []
        ),
        "context_provenance": {
            "event_identity_source": "complete_normalized_record",
            "record_body_resent": False,
        },
    }


def _pair_candidate(
    left: dict,
    right: dict,
    similarity: float,
    *,
    nomination_reasons: list[str],
) -> dict[str, Any]:
    left_key = clean_text(left.get("record_key")) or f"index_{left['_idx']}"
    right_key = clean_text(right.get("record_key")) or f"index_{right['_idx']}"
    pair_id = hashlib.sha1("|".join(sorted((left_key, right_key))).encode("utf-8")).hexdigest()[:14]
    title_overlap, title_jaccard = title_overlap_stats(left, right)
    story_overlap, story_jaccard, anchor_overlap = story_key_overlap_stats(left, right)
    return {
        "pair_id": f"pair_{pair_id}",
        "similarity": round(similarity, 6),
        "hours_apart": round(hours_between(left.get("published_at", ""), right.get("published_at", "")), 2),
        "title_overlap": title_overlap,
        "title_jaccard": round(title_jaccard, 4),
        "story_key_overlap": story_overlap,
        "story_key_jaccard": round(story_jaccard, 4),
        "anchor_overlap": anchor_overlap,
        "nomination_reasons": nomination_reasons,
        "left_record": _pair_record(left),
        "right_record": _pair_record(right),
        "_left_index": left["_idx"],
        "_right_index": right["_idx"],
    }


def build_record_context(record: dict) -> dict[str, Any]:
    full_record = _strip_internal_fields(record)
    content_fields = ("cleaned_content", "content", "transcript", "semantic_content", "raw_content")
    source_field = next(
        (field for field in content_fields if clean_text(record.get(field))),
        "",
    )
    semantic_content = str(record.get(source_field) or "").strip() if source_field else ""
    raw_content = str(record.get("raw_content") or "").strip()
    field_char_counts = {
        field: len(str(record.get(field) or ""))
        for field in content_fields
        if record.get(field) is not None
    }
    for field in content_fields:
        full_record.pop(field, None)
    full_record["semantic_content"] = semantic_content
    if raw_content and raw_content != semantic_content:
        full_record["distinct_raw_content"] = raw_content
    full_record["semantic_content_provenance"] = {
        "source_field": source_field,
        "complete": True,
        "truncated": False,
        "distinct_raw_content_included": bool(raw_content and raw_content != semantic_content),
        "original_field_char_counts": field_char_counts,
    }
    full_record["triage_story_keys"] = list(
        (record.get("editorial_triage") or {}).get("possible_story_keys") or []
    )
    return full_record


def _pair_record(record: dict) -> dict[str, Any]:
    return build_record_context(record)


def _triage_story_key_overlap(left: dict, right: dict) -> bool:
    left_keys = {
        clean_text(value).casefold()
        for value in (left.get("editorial_triage") or {}).get("possible_story_keys") or []
        if clean_text(value)
    }
    right_keys = {
        clean_text(value).casefold()
        for value in (right.get("editorial_triage") or {}).get("possible_story_keys") or []
        if clean_text(value)
    }
    return bool(left_keys & right_keys)


def _strip_pair_internals(candidate: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in candidate.items() if not key.startswith("_")}


def _attach_related_story_edges(clusters: list[dict], pair_decisions: list[dict]) -> None:
    story_by_record = {
        clean_text(record.get("record_key")): cluster
        for cluster in clusters
        for record in cluster.get("records", [])
        if clean_text(record.get("record_key"))
    }
    seen: set[tuple[str, str, str]] = set()
    for decision in pair_decisions:
        relationship = clean_text(decision.get("relationship"))
        if relationship not in {"follow_up", "broader_story_arc"}:
            continue
        left_story = story_by_record.get(clean_text(decision.get("left_record_key")))
        right_story = story_by_record.get(clean_text(decision.get("right_record_key")))
        if left_story is None or right_story is None or left_story is right_story:
            continue
        left_id = left_story["story_id"]
        right_id = right_story["story_id"]
        edge_key = tuple(sorted((left_id, right_id))) + (relationship,)
        if edge_key in seen:
            continue
        seen.add(edge_key)
        for current, related in ((left_story, right_story), (right_story, left_story)):
            current.setdefault("related_stories", []).append(
                {
                    "story_id": related["story_id"],
                    "relationship": relationship,
                    "confidence": decision.get("confidence", 0.0),
                    "reason": clean_text(decision.get("reason")),
                    "record_pair": [
                        clean_text(decision.get("left_record_key")),
                        clean_text(decision.get("right_record_key")),
                    ],
                }
            )


def _embed_texts(texts: list[str], model_name: str) -> np.ndarray:
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:  # pragma: no cover - import failure is explicit
        raise RuntimeError(
            "sentence-transformers is required for story_mapping semantic clustering."
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
            "time_span_hours": time_span_hours(first_seen, last_seen),
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
    score += int(_safe_int(record.get("stars", 0)) > 5000)
    score += int(_safe_int(record.get("score", 0)) > 100)
    return score


def _record_sort_key(record: dict) -> tuple[str, str]:
    return (record.get("published_at", ""), record.get("title", ""))


def _enrich_record(
    record: dict,
    idx: int,
    *,
    fingerprint_chunk_chars: int = 1_800,
    max_fingerprint_chunks: int = 128,
) -> dict:
    enriched = dict(record)
    enriched["_idx"] = idx
    enriched["_fingerprint_text"] = build_fingerprint_text(record)
    enriched["_fingerprint_chunks"] = build_fingerprint_chunks(
        record,
        chunk_chars=fingerprint_chunk_chars,
        max_chunks=max_fingerprint_chunks,
    )
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


def _safe_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    if left.size == 0 or right.size == 0:
        return 0.0
    return float(np.dot(left, right) / (np.linalg.norm(left) * np.linalg.norm(right)))


def _record_chunk_vectors(
    records: list[dict[str, Any]],
    *,
    embedding_model: str,
    embedder: EmbeddingFn,
) -> list[np.ndarray]:
    chunks_by_record = [list(record.get("_fingerprint_chunks") or []) for record in records]
    flat_chunks = [chunk for chunks in chunks_by_record for chunk in chunks]
    vectors = np.asarray(embedder(flat_chunks, embedding_model))
    if vectors.ndim == 1:
        vectors = vectors.reshape(-1, 1)

    # Small injected test embedders historically returned one vector per record.
    # Preserve that explicit dependency boundary while production embeds every chunk.
    if len(vectors) == len(records) and len(flat_chunks) != len(records):
        return [vectors[index : index + 1] for index in range(len(records))]
    if len(vectors) != len(flat_chunks):
        raise ValueError(
            "Embedding provider returned an unexpected vector count: "
            f"vectors={len(vectors)}, fingerprint_chunks={len(flat_chunks)}"
        )

    grouped: list[np.ndarray] = []
    cursor = 0
    for chunks in chunks_by_record:
        grouped.append(vectors[cursor : cursor + len(chunks)])
        cursor += len(chunks)
    return grouped


def _record_similarity(left: np.ndarray, right: np.ndarray) -> float:
    if left.size == 0 or right.size == 0:
        return 0.0
    return max(
        _cosine_similarity(left_vector, right_vector)
        for left_vector in left
        for right_vector in right
    )


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
