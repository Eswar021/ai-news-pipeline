from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from langchain_core.runnables import RunnableLambda

from src.pipeline.content.editorial_selection.formats.roundup import app as selection_app
from src.pipeline.content.editorial_selection.formats.roundup.contract import (
    CandidateScreenDraft,
    RoundupSlateDraft,
)
from src.pipeline.content.editorial_triage import app as triage_app
from src.pipeline.content.editorial_triage.contract import TriageBatchOutput
from src.pipeline.content.evidence_prep import run as run_evidence_prep
from src.pipeline.content.news_collection import app as news_app
from src.pipeline.content.news_collection import utils as news_utils
from src.pipeline.content.news_collection.collectors import (
    community_signals,
    company_blogs,
    tech_news,
    youtube_transcripts,
)
from src.pipeline.content.news_collection.utils import build_candidate_decision, build_record
from src.pipeline.content.story_mapping.clusterer import _pair_record, cluster_records
from src.pipeline.content.story_mapping import pair_adjudicator as pair_adjudicator_module
from src.pipeline.content.story_mapping.pair_adjudicator import (
    _candidate_batches,
    adjudicate_candidate_pairs,
)


FIXTURE = Path(__file__).parent / "fixtures" / "editorial_triage_reference" / "candidates.json"


def _records() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["records"]


def test_pair_context_deduplicates_content_aliases_without_clipping() -> None:
    marker = "SEMANTIC_TAIL_MUST_SURVIVE"
    body = ("complete normalized article body " * 900) + marker
    record = {
        "record_key": "record_large",
        "title": "Large source record",
        "content": body,
        "cleaned_content": body,
        "semantic_content": body,
        "raw_content": body,
        "custom_metadata": {"preserved": True},
        "editorial_triage": {"possible_story_keys": ["large source"]},
    }

    projected = _pair_record(record)

    assert marker in projected["semantic_content"]
    assert projected["semantic_content_provenance"]["complete"] is True
    assert projected["semantic_content_provenance"]["truncated"] is False
    assert projected["custom_metadata"] == {"preserved": True}
    assert projected["triage_story_keys"] == ["large source"]
    assert "content" not in projected
    assert "cleaned_content" not in projected
    assert "raw_content" not in projected

    candidate = {
        "pair_id": "pair_large",
        "left_record": projected,
        "right_record": {**projected, "record_key": "record_large_2"},
    }
    assert len(
        _candidate_batches(
            [candidate],
            batch_size=1,
            max_batch_chars=20_000,
            max_single_pair_chars=90_000,
        )
    ) == 1


def test_pair_adjudication_parallel_batches_preserve_candidate_order(monkeypatch) -> None:
    candidates = [
        {
            "pair_id": f"pair_{index}",
            "left_record": {"record_key": f"left_{index}", "semantic_content": "left"},
            "right_record": {"record_key": f"right_{index}", "semantic_content": "right"},
        }
        for index in range(4)
    ]

    def fake_invoke_batch(*, batch, batch_index, llm_calls, **_kwargs):
        llm_calls.append(
            {
                "module_name": "pair_adjudication",
                "metadata": {"batch_index": batch_index},
            }
        )
        return [
            {
                "pair_id": item["pair_id"],
                "relationship": "unrelated",
                "confidence": 1.0,
                "reason": "fixture",
                "decision_source": "llm",
            }
            for item in batch
        ]

    monkeypatch.setattr(pair_adjudicator_module, "_invoke_batch", fake_invoke_batch)
    llm_calls: list[dict] = []
    decisions = adjudicate_candidate_pairs(
        candidates,
        config={
            "batch_size": 1,
            "worker_count": 2,
            "max_attempts": 1,
            "max_batch_chars": 10_000,
            "max_single_pair_chars": 20_000,
        },
        llm=object(),
        system_prompt="fixture",
        llm_calls=llm_calls,
    )

    assert [item["pair_id"] for item in decisions] == [item["pair_id"] for item in candidates]
    assert [item["metadata"]["batch_index"] for item in llm_calls] == [1, 2, 3, 4]


def _evidence_input() -> dict:
    return {
        "run": {"run_id": "retention_fixture"},
        "config": {
            "collection_window": {
                "start": "2026-07-10T00:00:00Z",
                "end": "2026-07-12T00:00:00Z",
                "lookback_hours": 48,
            },
            "query_themes": ["AI agents", "LLM releases", "AI coding tools"],
        },
        "input": {
            "news_collection": {
                "status": "ok",
                "data": {"run_id": "retention_fixture", "records": _records()},
            }
        },
    }


def _triage_config() -> dict:
    return {
        "enabled": True,
        "mode": "authoritative",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "prompt_version": "v1",
        "temperature": 0.1,
        "batch_size": 3,
        "max_record_context_chars": 300_000,
        "max_batch_context_chars": 450_000,
        "max_attempts": 2,
        "channel": {
            "channel_name": "Fixture AI",
            "content_promise": "Useful AI news without hype.",
            "allowed_topics": ["AI agents", "AI coding tools"],
            "excluded_topics": ["crypto", "consumer deals"],
        },
    }


def _fake_decisions(*, batch: list[dict], batch_index: int, **_kwargs) -> list[dict]:
    decisions = []
    for record in batch:
        title = record["title"].casefold()
        if "bitcoin" in title or "save 40" in title:
            action = "quarantine"
            relevance = "none"
            content_type = "promotion_or_deal"
        elif not record.get("published_at"):
            action = "reserve"
            relevance = "medium"
            content_type = "product_release"
        else:
            action = "advance"
            relevance = "high"
            content_type = "community_project"
        decisions.append(
            {
                "record_key": record["record_key"],
                "topic_relevance": relevance,
                "newsworthiness": "medium",
                "audience_value": "medium",
                "content_usability": "usable",
                "likely_content_type": content_type,
                "novelty": "new",
                "confidence": 0.8,
                "reason": "Fixture semantic decision.",
                "possible_story_keys": [record["record_key"]],
                "recommended_action": action,
                "decision_source": "llm",
                "batch_index": batch_index,
            }
        )
    return decisions


def test_evidence_retains_semantic_quarantines_and_raw_content() -> None:
    result = run_evidence_prep(_evidence_input())

    assert result["status"] == "ok"
    assert result["data"]["record_count"] == 7
    candidates = {item["title"]: item for item in result["data"]["records"]}
    token_story = candidates[
        "Claude Code sends 33k tokens before reading the prompt; OpenCode sends 7k"
    ]
    assert token_story["raw_content"] == token_story["cleaned_content"]

    missing_date = candidates[
        "A useful model release with an unresolved publication date"
    ]
    assert missing_date["quality_flags"]["published_at_missing"] is True
    assert missing_date["preparation_warnings"] == ["missing_published_at"]

    for title in (
        "Save 40 percent on this Asus tablet today",
        "How to build durable memory for an AI agent",
        "A new reasoning model enters production",
    ):
        assert "legacy_filter_hints" not in candidates[title]
        assert candidates[title]["preparation_warnings"] == []

    outside = next(
        item
        for item in result["summary"]["excluded_records"]
        if item["title"] == "An older AI launch outside the frozen run window"
    )
    assert outside["exclude_reason"] == "outside_manifest_window"


def test_evidence_removes_decoded_pdf_binary_before_editorial_triage() -> None:
    payload = _evidence_input()
    payload["input"]["news_collection"]["data"]["records"] = [
        {
            "record_id": "pdf_binary_fixture",
            "source": "hackernews",
            "source_group": "community_signals",
            "source_type": "community_signal",
            "title": "A linked research preprint",
            "url": "https://example.com/preprint.pdf",
            "published_at": "2026-07-11T10:00:00Z",
            "description": "Readable metadata fallback for semantic triage.",
            "content": "%PDF-1.7 " + ("\ufffd\x00binary-stream " * 30_000),
        }
    ]

    result = run_evidence_prep(payload)
    record = result["data"]["records"][0]

    assert result["status"] == "ok"
    assert record["content"] == "Readable metadata fallback for semantic triage."
    assert record["cleaned_content"] == record["content"]
    assert record["raw_content"] == ""
    assert record["quality_flags"]["non_text_source_payload"] == "pdf_binary"
    assert record["preparation_warnings"] == ["non_text_source_payload"]
    assert record["content_cleaning"]["non_text_payload_detected"] is True
    assert record["content_cleaning"]["decoded_payload_sha256"]

    batches, telemetry = triage_app._complete_context_batches(
        result["data"]["records"],
        batch_size=10,
        max_record_context_chars=300_000,
        max_batch_context_chars=450_000,
    )
    assert len(batches) == 1
    assert telemetry["records_truncated"] is False
    assert max(telemetry["record_context_chars"].values()) < 10_000


def test_request_text_extracts_pdf_instead_of_decoding_response_bytes(monkeypatch) -> None:
    class Response:
        headers = {"Content-Type": "application/pdf"}
        content = b"%PDF-1.7 binary fixture"
        text = "%PDF-1.7 decoded binary noise"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(news_utils.requests, "get", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(
        news_utils,
        "extract_pdf_text",
        lambda payload: "Readable extracted PDF text" if payload.startswith(b"%PDF-") else "",
    )

    assert news_utils.request_text("https://example.com/preprint.pdf", timeout=5) == (
        "Readable extracted PDF text"
    )


def test_evidence_keeps_a_flagged_candidate_for_editorial_triage() -> None:
    payload = _evidence_input()
    payload["input"]["news_collection"]["data"]["records"] = [_records()[3]]
    result = run_evidence_prep(payload)
    assert result["status"] == "ok"
    assert result["data"]["record_count"] == 1
    assert result["handoff"]["ready_for_editorial_triage"] is True


def test_editorial_triage_includes_recoverable_collector_candidates(monkeypatch) -> None:
    evidence_result = run_evidence_prep(_evidence_input())
    monkeypatch.setattr(triage_app, "make_llm", lambda **_kwargs: object())
    monkeypatch.setattr(triage_app, "_invoke_batch", _fake_decisions)

    collector_candidate = build_candidate_decision(
        source_group="community_signals",
        source="hackernews",
        title="A semantically useful candidate missed by a lexical filter",
        url="https://example.com/missed",
        published_at="2026-07-11T10:00:00Z",
        decision="quarantined",
        reason_code="legacy_relevance_filter",
    )
    result = triage_app.run(
        {
            "run": {"run_id": "retention_fixture"},
            "config": _triage_config(),
            "input": {
                "evidence_prep": evidence_result,
                "news_collection": {
                    "data": {
                        "run_id": "retention_fixture",
                        "candidate_ledger": [collector_candidate],
                    }
                },
            },
        }
    )

    assert result["status"] == "ok"
    assert result["summary"]["decision_count"] == 8
    assert result["handoff"]["authoritative"] is True
    assert result["handoff"]["ready_for_story_mapping"] is True
    assert "record_" in result["data"]["pools"]["advance_record_keys"][0]


def test_editorial_triage_authoritatively_exposes_only_ai_eligible_story_records(monkeypatch) -> None:
    evidence_result = run_evidence_prep(_evidence_input())
    config = _triage_config()
    config.update(
        {
            "mode": "authoritative",
            "story_mapping_actions": ["advance", "reserve"],
        }
    )
    monkeypatch.setattr(triage_app, "make_llm", lambda **_kwargs: object())
    monkeypatch.setattr(triage_app, "_invoke_batch", _fake_decisions)

    result = triage_app.run(
        {
            "run": {"run_id": "retention_fixture"},
            "config": config,
            "input": {"evidence_prep": evidence_result},
        }
    )

    pools = result["data"]["pools"]
    decision_by_key = {item["record_key"]: item for item in result["data"]["decisions"]}
    assert result["handoff"]["authoritative"] is True
    assert result["handoff"]["ready_for_story_mapping"] is True
    assert pools["story_mapping_record_keys"]
    assert all(
        decision_by_key[key]["recommended_action"] in {"advance", "reserve"}
        for key in pools["story_mapping_record_keys"]
    )
    assert not set(pools["quarantine_record_keys"]) & set(pools["story_mapping_record_keys"])


def test_editorial_triage_can_be_disabled_without_provider_call(monkeypatch) -> None:
    evidence_result = run_evidence_prep(_evidence_input())
    config = _triage_config()
    config["enabled"] = False
    monkeypatch.setattr(
        triage_app,
        "make_llm",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("provider should not be created")),
    )
    result = triage_app.run(
        {
            "run": {"run_id": "retention_fixture"},
            "config": config,
            "input": {"evidence_prep": evidence_result},
        }
    )
    assert result["status"] == "ok"
    assert result["summary"]["disabled"] is True
    assert result["summary"]["llm_call_count"] == 0


def test_editorial_triage_uses_bounded_unresolved_fallback(monkeypatch) -> None:
    evidence_result = run_evidence_prep(_evidence_input())
    attempts = {"count": 0}

    def fail_batch(**_kwargs):
        attempts["count"] += 1
        raise RuntimeError("fixture provider failure")

    monkeypatch.setattr(triage_app, "make_llm", lambda **_kwargs: object())
    monkeypatch.setattr(triage_app, "_invoke_batch", fail_batch)
    result = triage_app.run(
        {
            "run": {"run_id": "retention_fixture"},
            "config": _triage_config(),
            "input": {"evidence_prep": evidence_result},
        }
    )

    assert result["status"] == "partial"
    assert attempts["count"] == 6
    assert result["summary"]["unresolved_count"] == 7
    assert result["handoff"]["ready_for_story_mapping"] is False
    assert all(item["recommended_action"] == "reserve" for item in result["data"]["decisions"])


def test_editorial_triage_structured_langchain_smoke() -> None:
    batch = [
        {
            "record_key": "record_fixture",
            "source": "fixture",
            "source_group": "community_signals",
            "source_type": "community_signal",
            "title": "A useful AI agent tool",
            "url": "https://example.com/tool",
            "published_at": "2026-07-11T00:00:00Z",
            "content": "A useful open-source AI agent tool.",
        }
    ]
    parsed = TriageBatchOutput.model_validate(
        {
            "decisions": [
                {
                    "record_key": "record_fixture",
                    "topic_relevance": "high",
                    "newsworthiness": "medium",
                    "audience_value": "high",
                    "content_usability": "usable",
                    "likely_content_type": "community_project",
                    "novelty": "new",
                    "confidence": 0.9,
                    "reason": "Useful and in scope.",
                    "possible_story_keys": ["agent_tool"],
                    "recommended_action": "advance",
                }
            ]
        }
    )

    class FakeLLM:
        def with_structured_output(self, output_model, include_raw):
            assert output_model is TriageBatchOutput
            assert include_raw is True
            return RunnableLambda(
                lambda _prompt: {"parsed": parsed, "raw": None, "parsing_error": None}
            )

    llm_calls = []
    decisions = triage_app._invoke_batch(
        batch=batch,
        batch_index=1,
        attempt=1,
        config=_triage_config(),
        prompt_bundle={"system": "System", "user_preamble": "User"},
        llm=FakeLLM(),
        llm_calls=llm_calls,
    )
    assert decisions[0]["recommended_action"] == "advance"
    assert len(llm_calls) == 1


def test_story_mapping_retains_weak_singletons() -> None:
    record = {
        "record_key": "record_weak",
        "source": "unknown",
        "source_group": "community_signals",
        "source_type": "community_signal",
        "title": "Small experiment",
        "url": "https://example.com/small",
        "published_at": "2026-07-11T00:00:00Z",
        "content": "A small experiment with limited engagement.",
    }
    clusters, stats = cluster_records(
        [record],
        {
            "embedding_model": "unused",
            "effective_max_pair_hours": 48,
            "candidate_neighbors_per_record": 4,
        },
        embedder=lambda _texts, _model: np.zeros((1, 1)),
    )
    assert len(clusters) == 1
    assert "dropped_singletons" not in stats


def test_cross_source_pair_adjudication_links_follow_up_without_merging() -> None:
    records = [
        {
            "record_key": "record_official",
            "source": "official",
            "source_group": "ai_company_blogs",
            "title": "Acme launches Agent One",
            "url": "https://acme.example/agent-one",
            "published_at": "2026-07-10T00:00:00Z",
            "content": "Acme launched Agent One for enterprise workflows.",
        },
        {
            "record_key": "record_report",
            "source": "news",
            "source_group": "tech_news_apis",
            "title": "Acme expands Agent One after launch",
            "url": "https://news.example/acme-agent-one",
            "published_at": "2026-07-11T00:00:00Z",
            "content": "A follow-up report describes the first expansion after launch.",
        },
    ]
    seen_pairs: list[dict] = []

    def adjudicate(pairs: list[dict]) -> list[dict]:
        seen_pairs.extend(pairs)
        return [
            {
                "pair_id": pair["pair_id"],
                "relationship": "follow_up",
                "confidence": 0.92,
                "reason": "The report is a later development, not the same launch event.",
                "decision_source": "fixture",
            }
            for pair in pairs
        ]

    clusters, stats = cluster_records(
        records,
        {
            "embedding_model": "unused",
            "effective_max_pair_hours": 48,
            "candidate_neighbors_per_record": 4,
            "max_candidate_pairs": 20,
        },
        embedder=lambda _texts, _model: np.asarray([[1.0, 0.0], [1.0, 0.0]]),
        pair_adjudicator=adjudicate,
    )

    assert len(seen_pairs) == 1
    assert {seen_pairs[0]["left_record"]["source_group"], seen_pairs[0]["right_record"]["source_group"]} == {
        "ai_company_blogs",
        "tech_news_apis",
    }
    assert len(clusters) == 2
    assert stats["pair_relationship_counts"] == {"follow_up": 1}
    assert all(cluster.get("related_stories") for cluster in clusters)


def test_semantic_candidates_stay_separate_when_pair_adjudication_is_disabled() -> None:
    records = [
        {
            "record_key": "record_left",
            "source": "official",
            "source_group": "ai_company_blogs",
            "title": "Acme launches Agent One",
            "url": "https://acme.example/agent-one",
            "published_at": "2026-07-10T00:00:00Z",
            "content": "Acme launched Agent One for enterprise workflows.",
        },
        {
            "record_key": "record_right",
            "source": "news",
            "source_group": "tech_news_apis",
            "title": "Acme launches Agent One for teams",
            "url": "https://news.example/acme-agent-one",
            "published_at": "2026-07-10T01:00:00Z",
            "content": "The report covers the Agent One launch for enterprise teams.",
        },
    ]

    clusters, stats = cluster_records(
        records,
        {
            "embedding_model": "unused",
            "effective_max_pair_hours": 48,
            "candidate_neighbors_per_record": 4,
            "max_candidate_pairs": 20,
        },
        embedder=lambda _texts, _model: np.asarray([[1.0, 0.0], [1.0, 0.0]]),
        pair_adjudicator=None,
    )

    assert len(clusters) == 2
    assert stats["semantic_edges"] == 0
    assert stats["pair_relationship_counts"] == {"uncertain": 1}
    assert all(not cluster.get("related_stories") for cluster in clusters)


def test_top_neighbor_retrieval_sends_complete_low_similarity_records_to_llm() -> None:
    records = [
        {
            "record_key": "record_left",
            "source": "official",
            "source_group": "ai_company_blogs",
            "title": "Acme reveals Project Lantern",
            "url": "https://acme.example/lantern",
            "published_at": "2026-07-10T00:00:00Z",
            "cleaned_content": "LEFT FULL CONTEXT " + "alpha " * 700,
            "editorial_triage": {"possible_story_keys": ["acme project lantern launch"]},
        },
        {
            "record_key": "record_right",
            "source": "news",
            "source_group": "tech_news_apis",
            "title": "A differently worded report about Acme's new system",
            "url": "https://news.example/acme-system",
            "published_at": "2026-07-10T02:00:00Z",
            "cleaned_content": "RIGHT FULL CONTEXT " + "beta " * 700,
            "editorial_triage": {"possible_story_keys": ["acme project lantern launch"]},
        },
    ]
    seen_pairs: list[dict] = []

    def adjudicate(pairs: list[dict]) -> list[dict]:
        seen_pairs.extend(pairs)
        return [
            {
                "pair_id": pair["pair_id"],
                "relationship": "same_event",
                "confidence": 0.9,
                "reason": "Complete records describe the same Project Lantern announcement.",
                "decision_source": "fixture",
            }
            for pair in pairs
        ]

    clusters, stats = cluster_records(
        records,
        {
            "embedding_model": "unused",
            "effective_max_pair_hours": 48,
            "candidate_neighbors_per_record": 1,
            "max_candidate_pairs": 20,
        },
        embedder=lambda _texts, _model: np.asarray([[1.0, 0.0], [0.0, 1.0]]),
        pair_adjudicator=adjudicate,
    )

    assert len(seen_pairs) == 1
    assert seen_pairs[0]["similarity"] == 0.0
    assert set(seen_pairs[0]["nomination_reasons"]) == {"shared_triage_story_key", "top_neighbor"}
    assert seen_pairs[0]["left_record"]["semantic_content"].endswith("alpha")
    assert seen_pairs[0]["right_record"]["semantic_content"].endswith("beta")
    assert seen_pairs[0]["left_record"]["semantic_content_provenance"]["truncated"] is False
    assert seen_pairs[0]["right_record"]["semantic_content_provenance"]["truncated"] is False
    assert len(clusters) == 1
    assert stats["candidate_covered_record_count"] == 2


def test_explicit_cross_pair_story_arc_blocks_transitive_same_event_merge() -> None:
    records = [
        {
            "record_key": f"record_{index}",
            "source": "fixture",
            "source_group": "tech_news_apis",
            "title": f"Acme event report {index}",
            "url": f"https://example.com/{index}",
            "published_at": f"2026-07-10T0{index}:00:00Z",
            "content": f"Complete report {index}.",
        }
        for index in range(3)
    ]

    def adjudicate(pairs: list[dict]) -> list[dict]:
        relationships = {
            frozenset(("record_0", "record_1")): "same_event",
            frozenset(("record_1", "record_2")): "same_event",
            frozenset(("record_0", "record_2")): "broader_story_arc",
        }
        return [
            {
                "pair_id": pair["pair_id"],
                "relationship": relationships[
                    frozenset((pair["left_record"]["record_key"], pair["right_record"]["record_key"]))
                ],
                "confidence": 0.9,
                "reason": "Fixture relationship.",
                "decision_source": "fixture",
            }
            for pair in pairs
        ]

    clusters, stats = cluster_records(
        records,
        {
            "embedding_model": "unused",
            "effective_max_pair_hours": 48,
            "candidate_neighbors_per_record": 2,
            "max_candidate_pairs": 20,
        },
        embedder=lambda _texts, _model: np.asarray([[1.0, 0.0], [0.9, 0.1], [0.8, 0.2]]),
        pair_adjudicator=adjudicate,
    )

    assert sorted(cluster["record_count"] for cluster in clusters) == [1, 2]
    assert stats["transitive_merge_rejection_count"] == 1


def test_missing_cross_pair_decision_does_not_veto_two_same_event_edges() -> None:
    records = [
        {
            "record_key": f"record_{index}",
            "source": "fixture",
            "source_group": "tech_news_apis",
            "title": f"Acme launch report {index}",
            "url": f"https://example.com/{index}",
            "published_at": f"2026-07-10T0{index}:00:00Z",
            "content": f"Complete report {index} about the same Acme launch.",
        }
        for index in range(3)
    ]
    seen_pairs: list[frozenset[str]] = []

    def adjudicate(pairs: list[dict]) -> list[dict]:
        seen_pairs.extend(
            frozenset(
                (
                    pair["left_record"]["record_key"],
                    pair["right_record"]["record_key"],
                )
            )
            for pair in pairs
        )
        return [
            {
                "pair_id": pair["pair_id"],
                "relationship": "same_event",
                "confidence": 0.9,
                "reason": "The complete records describe the same launch event.",
                "decision_source": "fixture",
            }
            for pair in pairs
        ]

    clusters, stats = cluster_records(
        records,
        {
            "embedding_model": "unused",
            "effective_max_pair_hours": 48,
            "candidate_neighbors_per_record": 1,
            "candidate_similarity_floor": 0.99,
            "max_candidate_pairs": 20,
        },
        embedder=lambda _texts, _model: np.asarray(
            [[1.0, 0.0], [0.8, 0.6], [0.0, 1.0]]
        ),
        pair_adjudicator=adjudicate,
    )

    assert set(seen_pairs) == {
        frozenset(("record_0", "record_1")),
        frozenset(("record_1", "record_2")),
    }
    assert len(clusters) == 1
    assert clusters[0]["record_count"] == 3
    assert stats["transitive_merge_rejection_count"] == 0


def test_editorial_selection_uses_structured_llm_and_preserves_full_stories(monkeypatch) -> None:
    stories = [
        {
            "story_id": f"story_{index}",
            "story_title": f"Story {index}",
            "story_identity": {"primary_entity": f"Entity {index}"},
            "records": [
                {
                    "record_key": f"record_{index}",
                    "source": "fixture",
                    "source_group": "tech_news_apis",
                    "title": f"Story {index}",
                    "url": f"https://example.com/{index}",
                    "content": f"Full source context for story {index}.",
                }
            ],
        }
        for index in range(1, 5)
    ]
    draft = RoundupSlateDraft.model_validate(
        {
            "episode_shape": "mixed_news_roundup",
            "episode_thesis": "",
            "ordering_rationale": "Lead with the clearest viewer payoff.",
            "selected": [
                {"story_id": "candidate_002", "role": "lead", "selection_reason": "Strong lead.", "viewer_payoff": "Useful.", "confidence": 0.9},
                {"story_id": "candidate_001", "role": "major", "selection_reason": "Strong follow-up.", "viewer_payoff": "Clear.", "confidence": 0.8},
                {"story_id": "candidate_004", "role": "brief", "selection_reason": "Good brief.", "viewer_payoff": "Timely.", "confidence": 0.75},
            ],
            "non_selected": [
                {"story_id": "candidate_003", "action": "reserve", "reason": "Useful next time.", "confidence": 0.7}
            ],
            "human_review_warning": "",
        }
    )

    class FakeLLM:
        def with_structured_output(self, output_model, include_raw):
            assert output_model is RoundupSlateDraft
            assert include_raw is True
            return RunnableLambda(
                lambda _prompt: {"parsed": draft, "raw": None, "parsing_error": None}
            )

    monkeypatch.setattr(selection_app, "make_llm", lambda **_kwargs: FakeLLM())
    result = selection_app.run(
        {
            "run": {"run_id": "selection_fixture"},
            "config": {
                "provider": "openai",
                "model": "fixture",
                "prompt_version": "v1",
                "min_stories": 3,
                "max_stories": 4,
                "max_candidate_stories": 10,
                "screening_shortlist_per_batch": 5,
                "max_story_context_chars": 500_000,
                "max_call_context_chars": 650_000,
                "max_attempts": 2,
                "channel": {"channel_name": "Fixture AI"},
            },
            "input": {
                "story_mapping": {
                    "status": "ok",
                    "data": {"run_id": "selection_fixture", "stories": stories},
                }
            },
        }
    )

    slate = result["data"]["editorial_slate"]
    assert result["status"] == "ok"
    assert slate["selected_story_ids"] == ["story_2", "story_1", "story_4"]
    assert slate["selected_stories"][0]["records"][0]["content"].startswith("Full source context")
    assert slate["reserve_stories"][0]["story_id"] == "story_3"


def test_editorial_selection_transports_opaque_refs_and_restores_canonical_ids() -> None:
    canonical_ids = [
        "story_20260715_build_a_multi_camera_3d_tracking_applica_bd5f8e",
        "story_20260715_gpt_red_unlocking_self_improvement_for_4c86c2",
    ]
    stories = [
        {
            "story_id": story_id,
            "story_title": f"Story {index}",
            "related_stories": [
                {
                    "story_id": canonical_ids[index % len(canonical_ids)],
                    "relationship": "follow_up",
                    "reason": "Useful semantic relation without transport identity.",
                }
            ],
            "records": [
                {
                    "record_key": f"record_{index}",
                    "title": f"Story {index}",
                    "url": f"https://example.com/{index}",
                    "content": "Complete source context.",
                }
            ],
        }
        for index, story_id in enumerate(canonical_ids, start=1)
    ]
    contexts, ref_map = selection_app._selection_contexts_with_refs(
        stories,
        {
            "model": "fixture",
            "tokenizer_encoding": "o200k_base",
            "max_story_context_chars": 500_000,
            "max_story_context_tokens": 90_000,
        },
    )

    assert [context["story_id"] for context in contexts] == [
        "candidate_001",
        "candidate_002",
    ]
    assert ref_map == {
        "candidate_001": canonical_ids[0],
        "candidate_002": canonical_ids[1],
    }
    serialized_context = json.dumps(contexts)
    assert all(story_id not in serialized_context for story_id in canonical_ids)

    restored = selection_app._restore_candidate_screen_story_ids(
        CandidateScreenDraft.model_validate(
            {
                "decisions": [
                    {
                        "story_id": "candidate_002",
                        "action": "shortlist",
                        "reason": "Stronger editorial fit.",
                        "confidence": 0.9,
                    }
                ]
            }
        ),
        ref_map,
    )
    assert restored.decisions[0].story_id == canonical_ids[1]


def test_editorial_selection_batches_complete_context_by_token_budget() -> None:
    stories = [
        {
            "story_id": f"story_{index}",
            "story_title": f"Story {index}",
            "records": [
                {
                    "record_key": f"record_{index}",
                    "title": f"Story {index}",
                    "url": f"https://example.com/{index}",
                    "content": (f"distinct_token_{index} " * 900).strip(),
                }
            ],
        }
        for index in range(1, 5)
    ]
    config = {
        "model": "fixture",
        "tokenizer_encoding": "o200k_base",
        "max_candidate_stories": 10,
        "max_story_context_chars": 500_000,
        "max_call_context_chars": 650_000,
        "max_story_context_tokens": 5_000,
        "max_call_context_tokens": 6_000,
    }

    batches = selection_app._balanced_context_batches(stories, config)

    assert len(batches) > 1
    assert sum(len(batch) for batch in batches) == len(stories)
    for batch in batches:
        contexts, _ref_map = selection_app._selection_contexts_with_refs(batch, config)
        _chars, tokens = selection_app._validate_call_context(contexts, config)
        assert tokens <= config["max_call_context_tokens"]


def test_editorial_selection_semantically_screens_overflow_without_dropping_by_code(
    monkeypatch,
) -> None:
    stories = [
        {
            "story_id": f"story_{index}",
            "story_title": f"Story {index}",
            "story_identity": {"primary_entity": f"Entity {index}"},
            "records": [
                {
                    "record_key": f"record_{index}",
                    "source": "fixture",
                    "source_group": "tech_news_apis",
                    "title": f"Story {index}",
                    "url": f"https://example.com/{index}",
                    "content": f"Full source context for story {index}.",
                }
            ],
        }
        for index in range(1, 12)
    ]
    screen_drafts = [
        CandidateScreenDraft.model_validate(
            {
                "decisions": [
                    {"story_id": "candidate_001", "action": "shortlist", "reason": "Strong.", "confidence": 0.9},
                    {"story_id": "candidate_002", "action": "shortlist", "reason": "Useful.", "confidence": 0.85},
                    {"story_id": "candidate_003", "action": "shortlist", "reason": "Clear.", "confidence": 0.8},
                ]
            }
        ),
        CandidateScreenDraft.model_validate(
            {
                "decisions": [
                    {"story_id": "candidate_001", "action": "shortlist", "reason": "Strong.", "confidence": 0.9},
                    {"story_id": "candidate_002", "action": "shortlist", "reason": "Useful.", "confidence": 0.85},
                    {"story_id": "candidate_003", "action": "shortlist", "reason": "Clear.", "confidence": 0.8},
                ]
            }
        ),
    ]
    final_draft = RoundupSlateDraft.model_validate(
        {
            "episode_shape": "mixed_news_roundup",
            "episode_thesis": "",
            "ordering_rationale": "Lead with the strongest viewer payoff.",
            "selected": [
                {"story_id": "candidate_001", "role": "lead", "selection_reason": "Lead.", "viewer_payoff": "High.", "confidence": 0.9},
                {"story_id": "candidate_004", "role": "major", "selection_reason": "Major.", "viewer_payoff": "High.", "confidence": 0.85},
                {"story_id": "candidate_002", "role": "brief", "selection_reason": "Brief.", "viewer_payoff": "Useful.", "confidence": 0.8},
            ],
            "non_selected": [
                {"story_id": "candidate_005", "action": "reserve", "reason": "Final alternate.", "confidence": 0.75},
                {"story_id": "candidate_003", "action": "reserve", "reason": "Final alternate.", "confidence": 0.7},
            ],
            "human_review_warning": "",
        }
    )

    class FakeLLM:
        def with_structured_output(self, output_model, include_raw):
            assert include_raw is True
            if output_model is CandidateScreenDraft:
                draft = screen_drafts.pop(0)
            else:
                assert output_model is RoundupSlateDraft
                draft = final_draft
            return RunnableLambda(
                lambda _prompt: {"parsed": draft, "raw": None, "parsing_error": None}
            )

    monkeypatch.setattr(selection_app, "make_llm", lambda **_kwargs: FakeLLM())
    result = selection_app.run(
        {
            "run": {"run_id": "selection_overflow_fixture"},
            "config": {
                "provider": "openai",
                "model": "fixture",
                "prompt_version": "v1",
                "min_stories": 3,
                "max_stories": 3,
                "max_candidate_stories": 6,
                "screening_shortlist_per_batch": 3,
                "max_screening_rounds": 2,
                "max_story_context_chars": 500_000,
                "max_call_context_chars": 650_000,
                "max_attempts": 2,
                "channel": {"channel_name": "Fixture AI"},
            },
            "input": {
                "story_mapping": {
                    "status": "ok",
                    "data": {
                        "run_id": "selection_overflow_fixture",
                        "stories": stories,
                    },
                }
            },
        }
    )

    slate = result["data"]["editorial_slate"]
    assert result["status"] == "ok"
    assert result["summary"]["evaluated_story_count"] == 11
    assert result["summary"]["screening_call_count"] == 2
    assert result["summary"]["llm_call_count"] == 3
    assert result["summary"]["final_candidate_story_count"] == 6
    assert result["summary"]["selection_strategy"] == "iterative_llm_screening_then_final_selection"
    assert slate["selected_story_ids"] == ["story_1", "story_2", "story_3"]
    assert len(slate["decision_ledger"]) == 11
    assert {item["story_id"] for item in slate["decision_ledger"]} == {
        story["story_id"] for story in stories
    }
    implicit_reserve = next(item for item in slate["reserve"] if item["story_id"] == "story_6")
    assert implicit_reserve["decision_source"] == "llm_selected_list_complement"
    assert result["summary"]["rejected_story_count"] == 0
    assert not screen_drafts


def test_github_uses_repository_activity_timestamp() -> None:
    assert community_signals._github_activity_time(
        {
            "pushed_at": "2026-07-11T10:00:00Z",
            "updated_at": "2026-07-12T10:00:00Z",
        }
    ) == "2026-07-11T10:00:00Z"


def test_github_search_does_not_require_a_star_floor(monkeypatch) -> None:
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"items": []}

    def fake_get(_url, **kwargs):
        captured.update(kwargs["params"])
        return Response()

    monkeypatch.setattr(community_signals.requests, "get", fake_get)
    community_signals._search_github_repos(
        "key",
        "AI agents",
        10,
        "2026-07-10",
    )
    assert "stars:" not in captured["q"]
    assert "pushed:>=2026-07-10" in captured["q"]


def test_hackernews_lexical_miss_is_collected_for_editorial_triage(monkeypatch) -> None:
    def fake_get_json(url: str, _timeout: int):
        if url.endswith("topstories.json"):
            return [101]
        return {
            "id": 101,
            "type": "story",
            "title": "A strange new developer workflow",
            "url": "https://example.com/workflow",
            "time": 1783700000,
            "score": 12,
            "descendants": 3,
            "by": "fixture",
        }

    monkeypatch.setattr(community_signals, "_get_json", fake_get_json)
    monkeypatch.setattr(community_signals, "request_text", lambda *_args, **_kwargs: "")
    result = community_signals._collect_hackernews(
        {
            "source_group": "community_signals",
            "query_themes": ["large language models"],
            "allowed_topics": ["AI"],
        },
        {"id": "hackernews", "story_type": "top"},
        timeout=2,
        max_items=1,
        scan_depth=1,
    )

    assert result["summary"]["collected_count"] == 1
    assert "legacy_relevance_match" not in result["records"][0]


def test_tech_feed_unsupported_body_url_remains_a_collected_record(monkeypatch) -> None:
    monkeypatch.setattr(
        tech_news,
        "_fetch_articles",
        lambda *_args, **_kwargs: [
            {
                "title": "A package with an unexpected AI use",
                "url": "https://pypi.org/project/example-package/",
                "published_at": "2026-07-11T00:00:00Z",
                "description": "A maintainer describes a new workflow.",
                "content": "",
                "source_name": "Fixture feed",
                "author": "Fixture",
            }
        ],
    )
    result = tech_news.collect(
        {
            "source_group": "tech_news_apis",
            "query_themes": ["large language models"],
            "allowed_topics": ["AI"],
            "collection_window": {
                "start": "2026-07-10T00:00:00+00:00",
                "end": "2026-07-12T00:00:00+00:00",
            },
            "runtime": {"max_items_per_source": 1},
            "sources": [
                {
                    "id": "fixture_feed",
                    "provider": "rss",
                    "enabled": True,
                    "collect_relevance_telemetry": True,
                    "source_type": "tech_news_article",
                }
            ],
        }
    )

    assert result["summary"]["collected_count"] == 1
    assert result["records"][0]["article_fetch_supported"] is False


def test_company_listing_suspicion_is_telemetry_not_an_eligibility_gate(monkeypatch) -> None:
    monkeypatch.setattr(
        company_blogs,
        "_fetch_entries",
        lambda *_args, **_kwargs: [
            {
                "title": "News",
                "url": "https://example.com/news",
                "published_at": "2026-07-11T00:00:00Z",
                "content": "A landing page that may still contain a useful announcement.",
                "summary": "Potentially useful source context.",
                "content_source": "entry_summary",
                "skip_article_fetch": True,
            }
        ],
    )
    result = company_blogs.collect(
        {
            "source_group": "ai_company_blogs",
            "runtime": {"max_items_per_source": 1},
            "sources": [
                {
                    "id": "fixture_company",
                    "name": "Fixture Company",
                    "enabled": True,
                    "source_type": "official_company_blog",
                }
            ],
        }
    )

    assert result["summary"]["collected_count"] == 1
    assert "listing_suspected" not in result["records"][0]


def test_youtube_retains_metadata_when_transcript_is_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("YOUTUBE_FIXTURE_KEY", "fixture")
    monkeypatch.setattr(
        youtube_transcripts,
        "_search_channel_videos",
        lambda *_args, **_kwargs: [
            {
                "video_id": "video-1",
                "title": "AI release explained",
                "description": "A useful description retained without a transcript.",
                "published_at": "2026-07-11T00:00:00Z",
            }
        ],
    )
    monkeypatch.setattr(
        youtube_transcripts,
        "_fetch_transcript",
        lambda _video_id: (_ for _ in ()).throw(RuntimeError("disabled")),
    )
    result = youtube_transcripts.collect(
        {
            "source_group": "youtube_podcast_transcripts",
            "env_keys": ["YOUTUBE_FIXTURE_KEY"],
            "collection_window": {
                "start": "2026-07-10T00:00:00Z",
                "end": "2026-07-12T00:00:00Z",
                "lookback_hours": 48,
            },
            "runtime": {"max_videos_per_channel": 1},
            "channels": [
                {
                    "id": "fixture_channel",
                    "name": "Fixture",
                    "channel_id": "fixture",
                    "enabled": True,
                }
            ],
        }
    )
    assert result["records"][0]["transcript_status"] == "unavailable"
    assert result["records"][0]["content"].startswith("A useful description")
    assert result["summary"]["status"] == "partial"


def test_youtube_search_uses_frozen_window_start(monkeypatch) -> None:
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"items": []}

    def fake_get(_url, **kwargs):
        captured.update(kwargs["params"])
        return Response()

    monkeypatch.setattr(youtube_transcripts.requests, "get", fake_get)
    youtube_transcripts._search_channel_videos(
        {"channel_id": "fixture"},
        "key",
        "2026-07-10T12:00:00+05:30",
        1,
        10,
    )
    assert captured["publishedAfter"] == "2026-07-10T06:30:00Z"


def test_news_collection_exposes_collected_and_quarantined_candidates(monkeypatch) -> None:
    accepted = build_record(
        source="fixture_source",
        source_group="tech_news_apis",
        source_type="tech_news_article",
        title="A useful AI release",
        url="https://example.com/release",
        published_at="2026-07-11T00:00:00Z",
        content="Useful release details.",
    )
    quarantined = build_candidate_decision(
        source_group="tech_news_apis",
        source="fixture_source",
        title="A candidate missed by the old filter",
        url="https://example.com/missed",
        published_at="2026-07-11T01:00:00Z",
        decision="quarantined",
        reason_code="legacy_relevance_filter",
    )
    monkeypatch.setattr(
        news_app,
        "_collect_group",
        lambda _group, _cfg: {
            "records": [accepted],
            "candidate_ledger": [quarantined],
            "summary": {"status": "ok", "collected_count": 1},
        },
    )
    result = news_app.run(
        {
            "run": {"run_id": "news_fixture"},
            "config": {
                "enabled_source_groups": ["tech_news_apis"],
                "query_themes": ["AI"],
                "collectors": {
                    "tech_news_apis": {
                        "source_group": "tech_news_apis",
                        "collection_window": {
                            "start": "2026-07-10T00:00:00Z",
                            "end": "2026-07-12T00:00:00Z",
                        },
                    }
                },
            },
            "input": {},
        }
    )
    assert result["data"]["record_count"] == 1
    assert result["data"]["candidate_count"] == 2
    assert result["summary"]["candidate_decision_counts"] == {
        "quarantined": 1,
        "collected": 1,
    }
