from __future__ import annotations

from datetime import datetime, timedelta, timezone
from collections import Counter
import time

from .collectors import (
    community_signals,
    company_blogs,
    research_papers,
    tech_news,
    youtube_transcripts,
)
from .contract import (
    NewsCollectionRequest,
    NewsCollectionResponse,
    NewsCollectionStatus,
)
from .utils import build_candidate_decision


IST = timezone(timedelta(hours=5, minutes=30))


def run(input_json: dict) -> dict:
    request = NewsCollectionRequest.model_validate(input_json)
    run_id = request.run.run_id
    started = time.time()

    records: list[dict] = []
    candidate_ledger: list[dict] = []
    group_summaries: dict[str, dict] = {}
    enabled_groups = list(request.config.enabled_source_groups)

    for group_name in enabled_groups:
        cfg = request.config.collectors[group_name].model_dump(mode="python")
        result = _collect_group(group_name, cfg)
        group_candidates = list(result.get("candidate_ledger", []))
        candidates_by_key = {
            item.get("candidate_key"): item
            for item in group_candidates
            if item.get("candidate_key")
        }
        for record in result["records"]:
            record["record_id"] = f"L1_{len(records) + 1:05d}"
            records.append(record)
            candidate = candidates_by_key.get(record.get("candidate_key"))
            if candidate is None:
                candidate = build_candidate_decision(
                    source_group=record.get("source_group", group_name),
                    source=record.get("source", ""),
                    title=record.get("title", ""),
                    url=record.get("url", ""),
                    published_at=record.get("published_at", ""),
                    decision="collected",
                    reason_code="collector_accepted",
                )
                group_candidates.append(candidate)
            candidate["decision"] = "collected"
            candidate["record_id"] = record["record_id"]
        candidate_ledger.extend(group_candidates)
        group_summaries[group_name] = result["summary"]

    generated_at = _iso_now()
    status = _overall_status(enabled_groups, group_summaries)
    successful_groups = [
        group_name
        for group_name, summary in group_summaries.items()
        if summary.get("collected_count", 0) > 0
    ]
    candidate_decision_counts = dict(
        Counter(item.get("decision", "unknown") for item in candidate_ledger)
    )
    response = NewsCollectionResponse(
        status=status,
        data={
            "run_id": run_id,
            "generated_at": generated_at,
            "record_count": len(records),
            "records": records,
            "candidate_count": len(candidate_ledger),
            "candidate_ledger": candidate_ledger,
        },
        summary={
            "run_id": run_id,
            "generated_at": generated_at,
            "status": status,
            "enabled_source_groups": enabled_groups,
            "enabled_source_group_count": len(enabled_groups),
            "successful_source_groups": successful_groups,
            "successful_source_group_count": len(successful_groups),
            "total_records": len(records),
            "candidate_count": len(candidate_ledger),
            "candidate_decision_counts": candidate_decision_counts,
            "elapsed_seconds": round(time.time() - started, 2),
            "groups": group_summaries,
        },
        handoff={
            "record_count": len(records),
            "candidate_count": len(candidate_ledger),
            "ready_for_evidence_prep": status in {"ok", "partial"} and len(records) > 0,
        },
    )
    return response.model_dump(mode="json")


def _collect_group(group_name: str, cfg: dict) -> dict:
    if group_name == "ai_company_blogs":
        return company_blogs.collect(cfg)
    if group_name == "tech_news_apis":
        return tech_news.collect(cfg)
    if group_name == "research_papers":
        return research_papers.collect(cfg)
    if group_name == "youtube_podcast_transcripts":
        return youtube_transcripts.collect(cfg)
    if group_name == "community_signals":
        return community_signals.collect(cfg)
    raise ValueError(f"Unsupported source group: {group_name}")


def _overall_status(enabled_groups: list[str], group_summaries: dict[str, dict]) -> NewsCollectionStatus:
    if not enabled_groups:
        return "ok"
    statuses = [group_summaries.get(group_name, {}).get("status") for group_name in enabled_groups]
    if statuses and all(status == "failed" for status in statuses):
        return "failed"
    if any(status != "ok" for status in statuses):
        return "partial"
    return "ok"


def _iso_now() -> str:
    return datetime.now(IST).isoformat()
