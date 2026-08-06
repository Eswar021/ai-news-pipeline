from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .cluster_reconciler import reconcile_components
from .clusterer import cluster_records
from .contract import StoryMappingRequest, StoryMappingResponse, StoryMappingStatus
from .event_identity import attach_event_identities
from src.pipeline.llm import make_llm
from .pair_adjudicator import adjudicate_candidate_pairs
from .prompt_loader import load_system_prompt
from .ranker import rank_stories
from .story_label import attach_story_labels
from .utils import clean_text


IST = timezone(timedelta(hours=5, minutes=30))


def run(input_json: dict) -> dict:
    request = StoryMappingRequest.model_validate(input_json)
    run_id = request.run.run_id
    records, triage_summary = _records_for_mapping(request)
    effective_max_pair_hours = _effective_max_pair_hours(request)
    cluster_cfg = _cluster_config(request, effective_max_pair_hours)

    llm_calls: list[dict[str, Any]] = []
    clusters: list[dict] = []
    cluster_stats = {
        "exact_match_edges": 0,
        "semantic_edges": 0,
    }

    event_identity_cfg = request.config.clustering.event_identity.model_dump(mode="json")
    event_identity_enabled = bool(event_identity_cfg["enabled"])
    event_identity_worker_count = int(event_identity_cfg.get("worker_count", 1))
    record_semantic_enricher = None
    if records and event_identity_enabled:
        event_identity_prompt = load_system_prompt(
            "event_identity",
            event_identity_cfg["prompt_version"],
        )
        event_identity_llm = make_llm(
            provider=event_identity_cfg["provider"],
            model=event_identity_cfg["model"],
            temperature=float(event_identity_cfg["temperature"]),
            base_url=event_identity_cfg.get("base_url"),
        )
        def record_semantic_enricher(candidate_records: list[dict]) -> list[dict]:
            return attach_event_identities(
                candidate_records,
                config=event_identity_cfg,
                llm=event_identity_llm,
                system_prompt=event_identity_prompt,
                llm_calls=llm_calls,
            )

    pair_adjudication_call_count = 0
    pair_confirmation_call_count = 0
    pair_adjudication_batch_count = 0
    pair_adjudication_worker_count = 0
    pair_adjudication_enabled = False
    pair_full_record_review_provider = ""
    pair_full_record_review_model = ""
    reconciliation_cfg = request.config.clustering.cluster_reconciliation.model_dump(
        mode="json"
    )
    reconciliation_enabled = bool(reconciliation_cfg["enabled"])
    reconciliation_worker_count = int(reconciliation_cfg.get("worker_count", 1))
    if records:
        pair_cfg = request.config.clustering.pair_adjudication.model_dump(mode="json")
        pair_adjudication_enabled = bool(pair_cfg["enabled"])
        pair_adjudication_worker_count = int(pair_cfg.get("worker_count", 2))
        pair_adjudicator = None
        if pair_cfg["enabled"]:
            pair_prompt = load_system_prompt("pair_adjudication", pair_cfg["prompt_version"])
            pair_llm = make_llm(
                provider=pair_cfg["provider"],
                model=pair_cfg["model"],
                temperature=float(pair_cfg["temperature"]),
                base_url=pair_cfg.get("base_url"),
            )
            full_record_llm = None
            full_record_cfg = dict(pair_cfg.get("full_record_review") or {})
            if full_record_cfg:
                pair_full_record_review_provider = clean_text(
                    full_record_cfg.get("provider")
                )
                pair_full_record_review_model = clean_text(full_record_cfg.get("model"))
                full_record_llm = make_llm(
                    provider=full_record_cfg["provider"],
                    model=full_record_cfg["model"],
                    temperature=float(full_record_cfg["temperature"]),
                    base_url=full_record_cfg.get("base_url"),
                )

            def pair_adjudicator(candidates: list[dict]) -> list[dict]:
                return adjudicate_candidate_pairs(
                    candidates,
                    config=pair_cfg,
                    llm=pair_llm,
                    system_prompt=pair_prompt,
                    llm_calls=llm_calls,
                    full_record_llm=full_record_llm,
                )

        cluster_reconciler = None
        if reconciliation_enabled:
            reconciliation_prompt = load_system_prompt(
                "cluster_reconciliation",
                reconciliation_cfg["prompt_version"],
            )
            conflict_resolution_prompt = load_system_prompt(
                "cluster_conflict_resolution",
                reconciliation_cfg["prompt_version"],
            )
            reconciliation_llm = make_llm(
                provider=reconciliation_cfg["provider"],
                model=reconciliation_cfg["model"],
                temperature=float(reconciliation_cfg["temperature"]),
                base_url=reconciliation_cfg.get("base_url"),
            )

            def cluster_reconciler(components: list[dict]) -> dict[str, list[list[str]]]:
                return reconcile_components(
                    components,
                    config=reconciliation_cfg,
                    llm=reconciliation_llm,
                    system_prompt=reconciliation_prompt,
                    conflict_system_prompt=conflict_resolution_prompt,
                    llm_calls=llm_calls,
                )

        clusters, cluster_stats = cluster_records(
            records,
            cluster_cfg,
            pair_adjudicator=pair_adjudicator,
            cluster_reconciler=cluster_reconciler,
            record_semantic_enricher=record_semantic_enricher,
        )
        pair_adjudication_call_count = sum(
            item.get("module_name") == "pair_adjudication" for item in llm_calls
        )
        pair_confirmation_call_count = sum(
            item.get("module_name") == "pair_adjudication_full_confirmation"
            for item in llm_calls
        )
        pair_adjudication_batch_count = len(
            {
                int((item.get("metadata") or {}).get("batch_index", 0))
                for item in llm_calls
                if item.get("module_name") == "pair_adjudication"
                and int((item.get("metadata") or {}).get("batch_index", 0)) > 0
            }
        )

    llm_story_label_count = 0
    story_label_worker_count = 0
    if clusters and request.config.use_llm_story_labels:
        story_label_cfg = request.config.story_label
        if story_label_cfg is None:
            raise ValueError("story_label config is required when use_llm_story_labels is true")
        story_label_dict = story_label_cfg.model_dump(mode="json")
        story_label_worker_count = int(story_label_dict["worker_count"])
        prompt = load_system_prompt("story_label", story_label_dict["prompt_version"])
        llm = make_llm(
            provider=story_label_dict.get("provider", "openai"),
            model=story_label_dict["model"],
            temperature=float(story_label_dict["temperature"]),
            base_url=story_label_dict.get("base_url"),
        )
        clusters = attach_story_labels(
            clusters,
            story_label_cfg=story_label_dict,
            run_context={
                "collection_window": request.config.collection_window.model_dump(mode="json"),
                "effective_max_pair_hours": effective_max_pair_hours,
            },
            llm=llm,
            llm_calls=llm_calls,
            system_prompt=prompt,
        )
        llm_story_label_count = len(clusters)

    ranking_config = request.config.ranking.model_dump(mode="json")
    ranked_stories = rank_stories(clusters, ranking_config)
    generated_at = _iso_now()
    status = _overall_status(len(records), len(ranked_stories))
    summary = _build_summary(
        run_id=run_id,
        generated_at=generated_at,
        status=status,
        input_count=len(records),
        stories=ranked_stories,
        cluster_stats=cluster_stats,
        effective_max_pair_hours=effective_max_pair_hours,
        ranking_authority="telemetry_only",
        triage_summary=triage_summary,
        use_llm_story_labels=bool(request.config.use_llm_story_labels),
        story_label_provider=(request.config.story_label.provider if request.config.story_label else ""),
        story_label_model=(request.config.story_label.model if request.config.story_label else ""),
        story_label_prompt_version=(request.config.story_label.prompt_version if request.config.story_label else ""),
        llm_story_label_count=llm_story_label_count,
        story_label_worker_count=story_label_worker_count,
        pair_adjudication_enabled=pair_adjudication_enabled,
        pair_adjudication_call_count=pair_adjudication_call_count,
        pair_adjudication_batch_count=pair_adjudication_batch_count,
        pair_adjudication_worker_count=pair_adjudication_worker_count,
        event_identity_enabled=event_identity_enabled,
        event_identity_call_count=sum(
            item.get("module_name") == "event_identity" for item in llm_calls
        ),
        event_identity_worker_count=event_identity_worker_count,
        pair_confirmation_call_count=pair_confirmation_call_count,
        reconciliation_enabled=reconciliation_enabled,
        reconciliation_call_count=sum(
            item.get("module_name") == "cluster_reconciliation" for item in llm_calls
        ),
        reconciliation_worker_count=reconciliation_worker_count,
    )
    summary["llm_runtime"]["pair_full_record_review_provider"] = (
        pair_full_record_review_provider
    )
    summary["llm_runtime"]["pair_full_record_review_model"] = (
        pair_full_record_review_model
    )

    response = StoryMappingResponse(
        status=status,
        data={
            "run_id": run_id,
            "generated_at": generated_at,
            "story_count": len(ranked_stories),
            "stories": ranked_stories,
        },
        summary=summary,
        handoff={
            "story_count": len(ranked_stories),
            "ready_for_editorial_selection": status == "ok" and len(ranked_stories) > 0,
        },
        llm_calls=llm_calls,
    )
    return response.model_dump(mode="json")


def _records_for_mapping(request: StoryMappingRequest) -> tuple[list[dict], dict[str, Any]]:
    evidence = request.input.evidence_prep.data
    policy = request.config.triage_policy
    triage = request.input.editorial_triage
    if triage is None:
        if policy.required:
            raise ValueError("input.editorial_triage is required by config.triage_policy")
        records = list(evidence.records)
        return records, {
            "authoritative": False,
            "input_candidate_count": len(evidence.records),
            "eligible_record_count": len(records),
            "missing_record_count": 0,
        }

    triage_run_id = clean_text(triage.data.run_id)
    if triage_run_id and triage_run_id != request.run.run_id:
        raise ValueError(
            f"story_mapping run_id mismatch: request={request.run.run_id}, editorial_triage={triage_run_id}"
        )
    authoritative = bool(triage.handoff.get("authoritative"))
    if policy.required and not authoritative:
        raise ValueError("editorial_triage must be authoritative for this story_mapping run")
    if policy.required and triage.status != "ok":
        raise ValueError(f"editorial_triage status is not usable: {triage.status}")
    if policy.required and not bool(triage.handoff.get("ready_for_story_mapping")):
        raise ValueError("editorial_triage handoff is not ready for story_mapping")

    prepared_records = list(evidence.records)
    records_by_key = {
        clean_text(record.get("record_key")): record
        for record in prepared_records
        if clean_text(record.get("record_key"))
    }
    eligible_actions = set(policy.eligible_actions)
    decisions = [
        decision
        for decision in triage.data.decisions
        if decision.get("recommended_action") in eligible_actions
        and bool(decision.get("record_available_for_story_mapping", True))
    ]
    selected: list[dict] = []
    missing: list[str] = []
    for decision in decisions:
        key = clean_text(decision.get("record_key"))
        record = records_by_key.get(key)
        if record is None:
            missing.append(key)
            continue
        selected.append({**record, "editorial_triage": dict(decision)})

    if policy.required and not selected:
        raise ValueError("authoritative editorial_triage produced no mappable advance/reserve records")
    return selected, {
        "authoritative": authoritative,
        "input_candidate_count": len(prepared_records),
        "eligible_record_count": len(selected),
        "advance_count": sum(item.get("recommended_action") == "advance" for item in decisions),
        "reserve_count": sum(item.get("recommended_action") == "reserve" for item in decisions),
        "missing_record_count": len(missing),
        "missing_record_keys": missing,
        "retrieval_required_record_count": len(
            triage.data.pools.get("retrieval_required_record_keys", [])
        ),
    }


def _effective_max_pair_hours(request: StoryMappingRequest) -> float:
    configured = request.config.clustering.max_pair_hours
    if configured is not None:
        return float(configured)
    return float(request.config.collection_window.lookback_hours)


def _cluster_config(request: StoryMappingRequest, effective_max_pair_hours: float) -> dict:
    clustering = request.config.clustering.model_dump(mode="json")
    return {
        "embedding_model": request.config.embedding_model,
        "effective_max_pair_hours": effective_max_pair_hours,
        "candidate_neighbors_per_record": clustering["candidate_neighbors_per_record"],
        "candidate_similarity_floor": clustering["candidate_similarity_floor"],
        "fingerprint_chunk_chars": clustering["fingerprint_chunk_chars"],
        "max_fingerprint_chunks_per_record": clustering[
            "max_fingerprint_chunks_per_record"
        ],
        "max_candidate_pairs": clustering["max_candidate_pairs"],
    }


def _overall_status(input_count: int, story_count: int) -> StoryMappingStatus:
    if input_count == 0 or story_count == 0:
        return "failed"
    return "ok"


def _build_summary(
    *,
    run_id: str,
    generated_at: str,
    status: StoryMappingStatus,
    input_count: int,
    stories: list[dict],
    cluster_stats: dict[str, int],
    effective_max_pair_hours: float,
    ranking_authority: str,
    triage_summary: dict[str, Any],
    use_llm_story_labels: bool,
    story_label_provider: str,
    story_label_model: str,
    story_label_prompt_version: str,
    llm_story_label_count: int,
    story_label_worker_count: int,
    pair_adjudication_enabled: bool,
    pair_adjudication_call_count: int,
    pair_adjudication_batch_count: int,
    pair_adjudication_worker_count: int,
    event_identity_enabled: bool,
    event_identity_call_count: int,
    event_identity_worker_count: int,
    pair_confirmation_call_count: int,
    reconciliation_enabled: bool,
    reconciliation_call_count: int,
    reconciliation_worker_count: int,
) -> dict:
    bucket_counts: dict[str, int] = {}
    source_group_mix: dict[str, int] = {}
    for story in stories:
        bucket = story.get("priority_bucket", "unranked")
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        for group in story["source_groups"]:
            source_group_mix[group] = source_group_mix.get(group, 0) + 1

    return {
        "run_id": run_id,
        "generated_at": generated_at,
        "status": status,
        "input_record_count": input_count,
        "story_count": len(stories),
        "single_record_story_count": sum(1 for story in stories if story["record_count"] == 1),
        "multi_record_story_count": sum(1 for story in stories if story["record_count"] > 1),
        "semantic_merge_count": cluster_stats["semantic_edges"],
        "semantic_candidate_pair_count": int(cluster_stats.get("candidate_pair_count", 0)),
        "adjudicated_pair_count": int(cluster_stats.get("adjudicated_pair_count", 0)),
        "unadjudicated_pair_count": max(
            0,
            int(cluster_stats.get("candidate_pair_count", 0))
            - int(cluster_stats.get("adjudicated_pair_count", 0)),
        ),
        "pair_relationship_counts": dict(cluster_stats.get("pair_relationship_counts", {})),
        "time_eligible_pair_count": int(cluster_stats.get("time_eligible_pair_count", 0)),
        "top_neighbor_pair_count": int(cluster_stats.get("top_neighbor_pair_count", 0)),
        "triage_key_pair_count": int(cluster_stats.get("triage_key_pair_count", 0)),
        "similarity_floor_pair_count": int(
            cluster_stats.get("similarity_floor_pair_count", 0)
        ),
        "candidate_covered_record_count": int(cluster_stats.get("candidate_covered_record_count", 0)),
        "truncated_candidate_pair_count": int(cluster_stats.get("truncated_candidate_pair_count", 0)),
        "transitive_merge_rejection_count": int(cluster_stats.get("transitive_merge_rejection_count", 0)),
        "reconciliation_component_count": int(
            cluster_stats.get("reconciliation_component_count", 0)
        ),
        "reconciled_group_count": int(cluster_stats.get("reconciled_group_count", 0)),
        "reconciliation_split_count": int(
            cluster_stats.get("reconciliation_split_count", 0)
        ),
        "effective_max_pair_hours": effective_max_pair_hours,
        "ranking_authority": ranking_authority,
        "priority_bucket_counts": bucket_counts,
        "source_group_mix": source_group_mix,
        "llm_runtime": {
            "use_llm_story_labels": use_llm_story_labels,
            "story_label_provider": story_label_provider,
            "story_label_model": story_label_model,
            "story_label_prompt_version": story_label_prompt_version,
            "story_label_worker_count": story_label_worker_count,
            "llm_story_label_count": llm_story_label_count,
            "pair_adjudication_enabled": pair_adjudication_enabled,
            "pair_adjudication_call_count": pair_adjudication_call_count,
            "pair_adjudication_batch_count": pair_adjudication_batch_count,
            "pair_adjudication_worker_count": pair_adjudication_worker_count,
            "pair_confirmation_call_count": pair_confirmation_call_count,
            "event_identity_enabled": event_identity_enabled,
            "event_identity_call_count": event_identity_call_count,
            "event_identity_worker_count": event_identity_worker_count,
            "cluster_reconciliation_enabled": reconciliation_enabled,
            "cluster_reconciliation_call_count": reconciliation_call_count,
            "cluster_reconciliation_worker_count": reconciliation_worker_count,
            "parallelized_steps": [
                step
                for step, enabled in (
                    ("event_identity", event_identity_enabled and event_identity_worker_count > 1),
                    ("pair_adjudication", pair_adjudication_enabled and pair_adjudication_worker_count > 1),
                    (
                        "cluster_reconciliation",
                        reconciliation_enabled and reconciliation_worker_count > 1,
                    ),
                    ("story_label", use_llm_story_labels and bool(stories)),
                )
                if enabled
            ],
            "serial_steps": [],
        },
        "top_story_quality_flags": _top_story_quality_flags(stories[:12]),
        "top_stories": [
            {
                "rank": story["rank"],
                "title": story["story_title"],
                "score": story.get("rank_score"),
                "record_count": story["record_count"],
                "quality_flags": _story_quality_flags(story),
            }
            for story in stories[:10]
        ],
        "triage": triage_summary,
    }


def _top_story_quality_flags(stories: list[dict]) -> dict:
    flags = {
        "low_editorial_value_count": 0,
        "tutorial_count": 0,
        "event_update_count": 0,
    }
    for story in stories:
        story_flags = _story_quality_flags(story)
        for key in flags:
            if story_flags.get(key.removesuffix("_count"), False):
                flags[key] += 1
    return flags


def _story_quality_flags(story: dict) -> dict:
    identity = story.get("story_identity") or {}
    return {
        "low_editorial_value": identity.get("editorial_value") == "low",
        "tutorial": bool(identity.get("is_tutorial") or story.get("story_type_hint") == "tutorial_or_demo"),
        "event_update": bool(identity.get("is_event_update") or story.get("story_type_hint") == "event_update"),
    }


def _iso_now() -> str:
    return datetime.now(IST).isoformat()
