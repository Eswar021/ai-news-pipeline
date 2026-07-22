from __future__ import annotations

from langchain_core.runnables import RunnableLambda
import numpy as np

from src.pipeline.content.editorial_selection.formats.roundup import app as selection_app
from src.pipeline.content.editorial_selection.formats.roundup.contract import (
    RoundupDuplicateAudit,
    RoundupSlateDraft,
    RoundupSlateReviewDraft,
)
from src.pipeline.content.story_mapping.clusterer import cluster_records
from src.pipeline.content.story_mapping.cluster_reconciler import (
    ComponentReconciliationOutput,
    ConflictResolutionOutput,
    reconcile_components,
)
from src.pipeline.content.story_mapping.event_identity import (
    EventIdentityOutput,
    attach_event_identities,
)
from src.pipeline.content.story_mapping.pair_adjudicator import (
    PairDecisionBatch,
    _invoke_batch,
)


def test_event_identity_reads_complete_record_context() -> None:
    marker = "EVENT_IDENTITY_FULL_CONTEXT_MARKER"
    parsed = EventIdentityOutput.model_validate(
        {
            "primary_entity": "Moonshot AI",
            "owning_org": "Moonshot AI",
            "product_or_project": "Kimi K3",
            "named_identity_supported": True,
            "canonical_named_entity": "Moonshot AI",
            "canonical_named_product": "Kimi K3",
            "identity_resolution": "explicit",
            "identity_evidence": ["The record names Moonshot AI and Kimi K3."],
            "entity_aliases": ["Moonshot AI"],
            "product_aliases": ["Kimi K3"],
            "event_action": "announced",
            "event_type": "announcement",
            "event_status": "announced",
            "event_date": "2026-07-17",
            "canonical_event": "Moonshot AI announces Kimi K3",
            "story_family": "Kimi K3 release cycle",
            "distinguishing_details": ["Weights were promised for later"],
            "event_fingerprint": ["Moonshot AI", "Kimi K3", "2026-07-17"],
        }
    )

    class FakeLLM:
        def with_structured_output(self, _output_model, **_kwargs):
            return RunnableLambda(
                lambda _prompt: {"parsed": parsed, "raw": None, "parsing_error": None}
            )

    llm_calls: list[dict] = []
    records = attach_event_identities(
        [
            {
                "record_key": "record_kimi",
                "title": "Kimi K3 is announced",
                "cleaned_content": f"Complete article body. {marker}",
            }
        ],
        config={
            "provider": "openai",
            "model": "fixture",
            "worker_count": 1,
            "max_attempts": 1,
            "max_record_chars": 100_000,
        },
        llm=FakeLLM(),
        system_prompt="Extract event identity.",
        llm_calls=llm_calls,
    )

    assert records[0]["story_mapping_event_identity"]["event_status"] == "announced"
    assert marker in llm_calls[0]["messages"][0]["content"]
    assert llm_calls[0]["metadata"]["record_truncated"] is False


def test_cluster_reconciler_uses_event_capsules_and_returns_partition() -> None:
    marker = "EVENT_IDENTITY_CAPSULE_MARKER"
    parsed = ComponentReconciliationOutput.model_validate(
        {
            "component_id": "component_fixture",
            "groups": [
                {
                    "group_ref": "group_1",
                    "record_keys": ["record_a", "record_b"],
                    "relationship": "same_event_coverage",
                    "canonical_event": "One release",
                    "rationale": "Both records cover the same release.",
                },
                {
                    "group_ref": "group_2",
                    "record_keys": ["record_c"],
                    "relationship": "standalone_record",
                    "canonical_event": "An unrelated historical article",
                    "rationale": "This record describes a different event.",
                },
            ],
        }
    )

    class FakeLLM:
        def with_structured_output(self, _output_model, **_kwargs):
            return RunnableLambda(
                lambda _prompt: {"parsed": parsed, "raw": None, "parsing_error": None}
            )

    llm_calls: list[dict] = []
    groups = reconcile_components(
        [
            {
                "component_id": "component_fixture",
                "context_mode": "event_identity_capsules_from_complete_records",
                "records": [
                    {
                        "record_key": "record_a",
                        "event_identity": {"distinguishing_details": [marker]},
                    },
                    {
                        "record_key": "record_b",
                        "event_identity": {"canonical_event": "One release"},
                    },
                    {
                        "record_key": "record_c",
                        "event_identity": {"canonical_event": "Other article"},
                    },
                ],
                "pair_decisions": [],
            }
        ],
        config={
            "provider": "openai",
            "model": "fixture",
            "worker_count": 1,
            "max_attempts": 1,
            "max_component_chars": 100_000,
            "max_component_tokens": 10_000,
            "tokenizer_encoding": "o200k_base",
        },
        llm=FakeLLM(),
        system_prompt="Reconcile records.",
        llm_calls=llm_calls,
    )

    assert groups == {
        "component_fixture": [["record_a", "record_b"], ["record_c"]]
    }
    assert marker in llm_calls[0]["messages"][0]["content"]
    assert llm_calls[0]["metadata"]["records_truncated"] is False
    assert llm_calls[0]["metadata"]["serialized_context_tokens"] > 0


def test_cluster_reconciler_normalizes_duplicate_key_inside_one_group() -> None:
    parsed = ComponentReconciliationOutput.model_validate(
        {
            "component_id": "component_fixture",
            "groups": [
                {
                    "group_ref": "group_1",
                    "record_keys": ["record_a", "record_a", "record_b"],
                    "relationship": "same_event_coverage",
                    "canonical_event": "One release",
                    "rationale": "Both records cover the same release.",
                }
            ],
        }
    )

    class FakeLLM:
        def with_structured_output(self, _output_model, **_kwargs):
            return RunnableLambda(
                lambda _prompt: {"parsed": parsed, "raw": None, "parsing_error": None}
            )

    llm_calls: list[dict] = []
    groups = reconcile_components(
        [_reconciliation_component_fixture()],
        config=_reconciliation_config_fixture(max_attempts=1),
        llm=FakeLLM(),
        system_prompt="Reconcile records.",
        llm_calls=llm_calls,
    )

    assert groups == {"component_fixture": [["record_a", "record_b"]]}
    assert llm_calls[0]["metadata"]["same_group_duplicate_record_keys_removed"] == [
        "record_a"
    ]


def test_cluster_reconciler_reprompts_cross_group_duplicate_with_exact_error() -> None:
    outputs = [
        ComponentReconciliationOutput.model_validate(
            {
                "component_id": "component_fixture",
                "groups": [
                    {
                        "group_ref": "group_1",
                        "record_keys": ["record_a", "record_b"],
                        "relationship": "same_event_coverage",
                        "canonical_event": "One release",
                        "rationale": "These records cover one release.",
                    },
                    {
                        "group_ref": "group_2",
                        "record_keys": ["record_b"],
                        "relationship": "standalone_record",
                        "canonical_event": "Duplicate assignment",
                        "rationale": "This is intentionally invalid fixture output.",
                    },
                ],
            }
        ),
        ConflictResolutionOutput.model_validate(
            {
                "component_id": "component_fixture",
                "decisions": [
                    {
                        "record_key": "record_b",
                        "selected_candidate_id": "candidate_1",
                        "rationale": "Record B belongs with the release coverage.",
                    }
                ],
            }
        ),
    ]

    class FakeLLM:
        def with_structured_output(self, _output_model, **_kwargs):
            return RunnableLambda(
                lambda _prompt: {
                    "parsed": outputs.pop(0),
                    "raw": None,
                    "parsing_error": None,
                }
            )

    llm_calls: list[dict] = []
    groups = reconcile_components(
        [_reconciliation_component_fixture()],
        config=_reconciliation_config_fixture(max_attempts=2),
        llm=FakeLLM(),
        system_prompt="Reconcile records.",
        conflict_system_prompt="Resolve only the conflicting record assignment.",
        llm_calls=llm_calls,
    )

    assert groups == {"component_fixture": [["record_a", "record_b"]]}
    assert len(llm_calls) == 2
    assert "conflicting_assignments" in llm_calls[0]["metadata"]["parse_error"]
    assert llm_calls[1]["module_name"] == "cluster_reconciliation_conflict_resolution"
    assert '"candidate_id": "candidate_1"' in llm_calls[1]["messages"][0]["content"]
    assert llm_calls[1]["metadata"]["structural_repair_feedback_included"] is False


def _reconciliation_component_fixture() -> dict:
    return {
        "component_id": "component_fixture",
        "context_mode": "event_identity_capsules_from_complete_records",
        "records": [
            {
                "record_key": "record_a",
                "event_identity": {"canonical_event": "One release"},
            },
            {
                "record_key": "record_b",
                "event_identity": {"canonical_event": "One release"},
            },
        ],
        "pair_decisions": [],
    }


def _reconciliation_config_fixture(*, max_attempts: int) -> dict:
    return {
        "provider": "openai",
        "model": "fixture",
        "worker_count": 1,
        "max_attempts": max_attempts,
        "max_component_chars": 100_000,
        "max_component_tokens": 10_000,
        "tokenizer_encoding": "o200k_base",
    }


def test_pair_adjudication_uses_capsule_then_complete_record_confirmation() -> None:
    marker = "FULL_RECORD_CONFIRMATION_MARKER"
    candidate = {
        "pair_id": "pair_fixture",
        "similarity": 0.91,
        "left_record": {
            "record_key": "record_left",
            "title": "Kimi K3 is announced",
            "semantic_content": f"Official details {marker}",
            "story_mapping_event_identity": {
                "canonical_event": "Moonshot announces Kimi K3",
                "event_status": "announced",
            },
        },
        "right_record": {
            "record_key": "record_right",
            "title": "A preview of Kimi K3",
            "semantic_content": "Independent preview details",
            "story_mapping_event_identity": {
                "canonical_event": "Moonshot announces Kimi K3",
                "event_status": "reported",
            },
        },
    }
    outputs = [
        PairDecisionBatch.model_validate(
            {
                "decisions": [
                    {
                        "pair_id": "pair_fixture",
                        "relationship": "same_event",
                        "confidence": 0.91,
                        "reason": "The capsules identify the same launch.",
                        "requires_full_record_review": False,
                    }
                ]
            }
        ),
        PairDecisionBatch.model_validate(
            {
                "decisions": [
                    {
                        "pair_id": "pair_fixture",
                        "relationship": "same_event",
                        "confidence": 0.97,
                        "reason": "The complete records confirm the same event.",
                        "requires_full_record_review": False,
                    }
                ]
            }
        ),
    ]

    class FakeLLM:
        def with_structured_output(self, _output_model, **_kwargs):
            parsed = outputs.pop(0)
            return RunnableLambda(
                lambda _prompt: {"parsed": parsed, "raw": None, "parsing_error": None}
            )

    llm_calls: list[dict] = []
    decisions = _invoke_batch(
        batch=[candidate],
        batch_index=1,
        attempt=1,
        config={
            "provider": "openai",
            "model": "fixture",
            "confirm_same_event_with_full_records": True,
        },
        llm=FakeLLM(),
        system_prompt="Judge one pair.",
        llm_calls=llm_calls,
    )

    assert decisions[0]["relationship"] == "same_event"
    assert [call["module_name"] for call in llm_calls] == [
        "pair_adjudication",
        "pair_adjudication_full_confirmation",
    ]
    assert marker not in llm_calls[0]["messages"][0]["content"]
    assert marker in llm_calls[1]["messages"][0]["content"]


def test_pair_adjudication_honors_semantic_request_for_full_record_review() -> None:
    marker = "INDIRECT_IDENTITY_FULL_CONTEXT"
    candidate = {
        "pair_id": "pair_indirect_identity",
        "similarity": 0.8,
        "left_record": {
            "record_key": "record_named",
            "title": "Moonshot releases Kimi K3",
            "semantic_content": "Moonshot released Kimi K3.",
            "story_mapping_event_identity": {
                "primary_entity": "Moonshot AI",
                "product_or_project": "Kimi K3",
                "identity_resolution": "explicit",
                "event_fingerprint": ["largest open model", "stocks slid"],
            },
        },
        "right_record": {
            "record_key": "record_digest",
            "title": "China's latest AI leap",
            "url": "https://example.com/china-moonshot-ai",
            "semantic_content": f"A Chinese startup released the largest open model. {marker}",
            "story_mapping_event_identity": {
                "primary_entity": "Chinese startup",
                "product_or_project": "largest open model",
                "identity_resolution": "descriptive_only",
                "event_fingerprint": ["largest open model", "stocks slid"],
            },
        },
    }
    outputs = [
        PairDecisionBatch.model_validate(
            {
                "decisions": [
                    {
                        "pair_id": "pair_indirect_identity",
                        "relationship": "uncertain",
                        "confidence": 0.7,
                        "reason": "The generic identity needs complete-record review.",
                        "requires_full_record_review": True,
                    }
                ]
            }
        ),
        PairDecisionBatch.model_validate(
            {
                "decisions": [
                    {
                        "pair_id": "pair_indirect_identity",
                        "relationship": "same_event",
                        "confidence": 0.95,
                        "reason": "The complete records identify the same Kimi K3 launch.",
                        "requires_full_record_review": False,
                    }
                ]
            }
        ),
    ]

    class FakeLLM:
        def with_structured_output(self, _output_model, **_kwargs):
            parsed = outputs.pop(0)
            return RunnableLambda(
                lambda _prompt: {"parsed": parsed, "raw": None, "parsing_error": None}
            )

    llm_calls: list[dict] = []
    decisions = _invoke_batch(
        batch=[candidate],
        batch_index=1,
        attempt=1,
        config={
            "provider": "openai",
            "model": "fixture",
            "confirm_same_event_with_full_records": True,
            "review_ambiguous_pairs_with_full_records": True,
        },
        llm=FakeLLM(),
        system_prompt="Judge indirect event identity.",
        llm_calls=llm_calls,
    )

    assert decisions[0]["relationship"] == "same_event"
    assert marker not in llm_calls[0]["messages"][0]["content"]
    assert marker in llm_calls[1]["messages"][0]["content"]


def test_cluster_reconciliation_splits_unrelated_record_from_event_component() -> None:
    records = [
        {
            "record_key": record_key,
            "source": "fixture",
            "source_group": "tech_news_apis",
            "title": title,
            "url": f"https://example.com/{record_key}",
            "published_at": f"2026-07-17T0{index}:00:00Z",
            "content": title + (" FULL_ARTICLE_BODY" * 100),
            "story_mapping_event_identity": {
                "canonical_event": title,
                "story_family": "Kimi K3" if "Kimi" in title else "Comic Chat",
                "distinguishing_details": [f"identity_{record_key}"],
            },
        }
        for index, (record_key, title) in enumerate(
            (
                ("kimi_official", "Moonshot announces Kimi K3"),
                ("kimi_preview", "Previewing the Kimi K3 release"),
                ("kimi_report", "What the Kimi K3 announcement means"),
                ("comic_chat", "The history of Microsoft Comic Chat"),
            )
        )
    ]

    def adjudicate(pairs: list[dict]) -> list[dict]:
        relationships = {
            frozenset(("kimi_official", "kimi_preview")): "same_event",
            frozenset(("kimi_official", "kimi_report")): "same_event",
            frozenset(("kimi_preview", "kimi_report")): "broader_story_arc",
            # Deliberately reproduce the bad edge from the observed run.
            frozenset(("kimi_report", "comic_chat")): "same_event",
        }
        return [
            {
                "pair_id": pair["pair_id"],
                "relationship": relationships.get(
                    frozenset(
                        (
                            pair["left_record"]["record_key"],
                            pair["right_record"]["record_key"],
                        )
                    ),
                    "unrelated",
                ),
                "confidence": 0.9,
                "reason": "Fixture pair decision.",
                "decision_source": "fixture",
            }
            for pair in pairs
        ]

    seen_components: list[dict] = []

    def reconcile(components: list[dict]) -> dict[str, list[list[str]]]:
        seen_components.extend(components)
        assert all("semantic_content" not in record for record in components[0]["records"])
        assert all(record.get("event_identity") for record in components[0]["records"])
        component_id = components[0]["component_id"]
        return {
            component_id: [
                ["kimi_official", "kimi_preview", "kimi_report"],
                ["comic_chat"],
            ]
        }

    clusters, stats = cluster_records(
        records,
        {
            "embedding_model": "unused",
            "effective_max_pair_hours": 48,
            "candidate_neighbors_per_record": 3,
            "candidate_similarity_floor": 0.0,
            "max_candidate_pairs": 20,
        },
        embedder=lambda _texts, _model: np.asarray(
            [[1.0, 0.0], [1.0, 0.0], [1.0, 0.0], [1.0, 0.0]]
        ),
        pair_adjudicator=adjudicate,
        cluster_reconciler=reconcile,
    )

    assert len(seen_components) == 1
    assert sorted(cluster["record_count"] for cluster in clusters) == [1, 3]
    kimi_cluster = next(cluster for cluster in clusters if cluster["record_count"] == 3)
    assert {record["record_key"] for record in kimi_cluster["records"]} == {
        "kimi_official",
        "kimi_preview",
        "kimi_report",
    }
    assert stats["reconciliation_component_count"] == 1
    assert stats["reconciliation_split_count"] == 1
    assert stats["transitive_merge_rejection_count"] == 1


def test_follow_up_edge_does_not_create_reconciliation_component() -> None:
    records = [
        {
            "record_key": "launch",
            "source_group": "tech_news_apis",
            "title": "Acme launches Agent One",
            "url": "https://example.com/launch",
            "published_at": "2026-07-17T00:00:00Z",
            "content": "Agent One launched.",
        },
        {
            "record_key": "follow_up",
            "source_group": "tech_news_apis",
            "title": "Acme expands Agent One",
            "url": "https://example.com/follow-up",
            "published_at": "2026-07-17T01:00:00Z",
            "content": "A later expansion followed the launch.",
        },
    ]

    def adjudicate(pairs: list[dict]) -> list[dict]:
        return [
            {
                "pair_id": pair["pair_id"],
                "relationship": "follow_up",
                "confidence": 0.95,
                "reason": "This is a distinct later event.",
                "decision_source": "fixture",
            }
            for pair in pairs
        ]

    reconciliation_called = False

    def reconcile(_components: list[dict]) -> dict[str, list[list[str]]]:
        nonlocal reconciliation_called
        reconciliation_called = True
        return {}

    clusters, stats = cluster_records(
        records,
        {
            "embedding_model": "unused",
            "effective_max_pair_hours": 48,
            "candidate_neighbors_per_record": 1,
            "candidate_similarity_floor": 0.0,
            "max_candidate_pairs": 10,
        },
        embedder=lambda _texts, _model: np.asarray([[1.0, 0.0], [1.0, 0.0]]),
        pair_adjudicator=adjudicate,
        cluster_reconciler=reconcile,
    )

    assert reconciliation_called is False
    assert len(clusters) == 2
    assert stats["reconciliation_component_count"] == 0
    assert all(cluster.get("related_stories") for cluster in clusters)


def test_final_slate_review_replaces_duplicate_story(monkeypatch) -> None:
    stories = [
        {
            "story_id": f"story_{index}",
            "story_title": title,
            "records": [
                {
                    "record_key": f"record_{index}",
                    "title": title,
                    "url": f"https://example.com/{index}",
                    "content": f"Complete source context for {title}.",
                }
            ],
        }
        for index, title in enumerate(
            ("Kimi K3 launch", "Kimi K3 preview", "GPT-Red", "New hardware"),
            start=1,
        )
    ]
    selector_draft = RoundupSlateDraft.model_validate(
        {
            "episode_shape": "mixed_news_roundup",
            "episode_thesis": "",
            "ordering_rationale": "Initial slate.",
            "selected": [
                {"story_id": "candidate_001", "role": "lead", "selection_reason": "Lead.", "viewer_payoff": "Kimi.", "confidence": 0.9},
                {"story_id": "candidate_002", "role": "major", "selection_reason": "Second Kimi.", "viewer_payoff": "More Kimi.", "confidence": 0.8},
                {"story_id": "candidate_003", "role": "brief", "selection_reason": "Security.", "viewer_payoff": "Useful.", "confidence": 0.8},
            ],
            "non_selected": [
                {"story_id": "candidate_004", "action": "reserve", "reason": "Alternate.", "confidence": 0.7}
            ],
            "human_review_warning": "",
        }
    )
    duplicate_audit = RoundupDuplicateAudit.model_validate(
        {
            "assessments": [
                {
                    "story_id": "candidate_001",
                    "event_summary": "Moonshot releases Kimi K3.",
                    "duplicate_group_id": "duplicate_1",
                    "reason": "Named coverage of the Kimi K3 launch.",
                },
                {
                    "story_id": "candidate_002",
                    "event_summary": "A digest previews the same Kimi K3 launch.",
                    "duplicate_group_id": "duplicate_1",
                    "reason": "Indirect coverage of the same release cycle.",
                },
                {
                    "story_id": "candidate_003",
                    "event_summary": "A distinct GPT-Red story.",
                    "duplicate_group_id": "",
                    "reason": "Different event and product.",
                },
            ],
            "duplicate_story_groups": [
                {
                    "group_id": "duplicate_1",
                    "story_ids": ["candidate_001", "candidate_002"],
                    "relationship": "same_editorial_story",
                    "preferred_story_id": "candidate_001",
                    "reason": "Both stories cover the Kimi K3 launch.",
                }
            ],
            "audit_summary": "One duplicate group was found.",
        }
    )
    reviewer_draft = RoundupSlateReviewDraft.model_validate(
        {
            "episode_shape": "mixed_news_roundup",
            "episode_thesis": "",
            "ordering_rationale": "Remove duplicate Kimi coverage.",
            "selected": [
                {"story_id": "candidate_001", "role": "lead", "selection_reason": "Stronger Kimi context.", "viewer_payoff": "Kimi.", "confidence": 0.95},
                {"story_id": "candidate_003", "role": "major", "selection_reason": "Distinct security story.", "viewer_payoff": "Useful.", "confidence": 0.85},
                {"story_id": "candidate_004", "role": "brief", "selection_reason": "Distinct hardware story.", "viewer_payoff": "Useful.", "confidence": 0.8},
            ],
            "non_selected": [
                {"story_id": "candidate_002", "action": "reserve", "reason": "Duplicate Kimi event.", "confidence": 0.95}
            ],
            "human_review_warning": "",
            "review_changed": True,
            "review_reason": "Two proposed stories covered the same Kimi release.",
            "duplicate_story_groups": [
                {
                    "story_ids": ["candidate_001", "candidate_002"],
                    "relationship": "same_editorial_story",
                    "reason": "Both cover the same Kimi K3 release cycle.",
                }
            ],
        }
    )

    class FakeLLM:
        def with_structured_output(self, output_model, include_raw):
            assert include_raw is True
            if output_model is RoundupSlateDraft:
                parsed = selector_draft
            elif output_model is RoundupDuplicateAudit:
                parsed = duplicate_audit
            else:
                parsed = reviewer_draft
            return RunnableLambda(
                lambda _prompt: {"parsed": parsed, "raw": None, "parsing_error": None}
            )

    monkeypatch.setattr(selection_app, "make_llm", lambda **_kwargs: FakeLLM())
    result = selection_app.run(
        {
            "run": {"run_id": "slate_review_fixture"},
            "config": {
                "provider": "openai",
                "model": "fixture",
                "prompt_version": "v1",
                "min_stories": 3,
                "max_stories": 3,
                "max_candidate_stories": 10,
                "screening_shortlist_per_batch": 5,
                "max_attempts": 2,
                "channel": {"channel_name": "Fixture AI"},
                "slate_review": {
                    "enabled": True,
                    "prompt_version": "v1",
                    "max_attempts": 2,
                    "duplicate_audit_enabled": True,
                    "duplicate_audit_prompt_version": "v1",
                },
            },
            "input": {
                "story_mapping": {
                    "status": "ok",
                    "data": {"run_id": "slate_review_fixture", "stories": stories},
                }
            },
        }
    )

    assert result["status"] == "ok"
    assert result["data"]["editorial_slate"]["selected_story_ids"] == [
        "story_1",
        "story_3",
        "story_4",
    ]
    assert result["summary"]["slate_review_changed"] is True
    assert result["summary"]["duplicate_story_group_count"] == 1
    assert result["summary"]["focused_duplicate_group_count"] == 1


def test_editorial_screening_preserves_wide_finalist_target() -> None:
    stories = [{"story_id": f"story_{index}"} for index in range(18)]

    target_total = selection_app._screening_target_total(
        stories=stories,
        batch_sizes=[9, 9],
        shortlist_per_batch=15,
        config={
            "model": "fixture",
            "tokenizer_encoding": "o200k_base",
            "min_stories": 3,
            "max_stories": 5,
            "max_candidate_stories": 40,
            "target_finalist_stories": 12,
            "max_call_context_chars": 650_000,
            "max_call_context_tokens": 100_000,
        },
    )

    assert target_total == 12
    assert selection_app._screening_quotas(
        [9, 9],
        shortlist_per_batch=15,
        target_total=target_total,
    ) == [6, 6]


def test_final_slate_review_can_recover_late_semantic_reserve(monkeypatch) -> None:
    stories = [
        {
            "story_id": f"story_{index}",
            "story_title": f"Story {index}",
            "records": [
                {
                    "record_key": f"record_{index}",
                    "title": f"Story {index}",
                    "url": f"https://example.com/{index}",
                    "content": f"Complete source context for story {index}.",
                }
            ],
        }
        for index in range(1, 7)
    ]

    def fake_screen_candidate_pool(**_kwargs):
        return (
            stories[:4],
            [
                {
                    "story_id": "story_5",
                    "action": "reserve",
                    "reason": "Late semantic reserve.",
                    "selection_stage": "candidate_screen",
                    "decision_source": "llm_shortlist_complement",
                    "screening_round": 3,
                    "screening_batch": 1,
                },
                {
                    "story_id": "story_6",
                    "action": "reserve",
                    "reason": "Early semantic reserve.",
                    "selection_stage": "candidate_screen",
                    "decision_source": "llm_shortlist_complement",
                    "screening_round": 1,
                    "screening_batch": 1,
                },
            ],
            {
                "strategy": "fixture_semantic_screening",
                "input_story_count": 6,
                "final_candidate_story_count": 4,
                "target_finalist_story_count": 4,
                "rounds": [],
            },
        )

    selector_draft = RoundupSlateDraft.model_validate(
        {
            "episode_shape": "mixed_news_roundup",
            "episode_thesis": "",
            "ordering_rationale": "Initial finalist slate.",
            "selected": [
                {"story_id": "candidate_001", "role": "lead", "selection_reason": "Lead.", "viewer_payoff": "Useful.", "confidence": 0.9},
                {"story_id": "candidate_002", "role": "major", "selection_reason": "Major.", "viewer_payoff": "Useful.", "confidence": 0.85},
                {"story_id": "candidate_003", "role": "brief", "selection_reason": "Brief.", "viewer_payoff": "Useful.", "confidence": 0.8},
            ],
            "non_selected": [
                {"story_id": "candidate_004", "action": "reserve", "reason": "Alternate.", "confidence": 0.7}
            ],
            "human_review_warning": "",
        }
    )
    reviewer_draft = RoundupSlateReviewDraft.model_validate(
        {
            "episode_shape": "mixed_news_roundup",
            "episode_thesis": "",
            "ordering_rationale": "Promote the stronger late-stage reserve.",
            "selected": [
                {"story_id": "candidate_001", "role": "lead", "selection_reason": "Lead.", "viewer_payoff": "Useful.", "confidence": 0.9},
                {"story_id": "candidate_002", "role": "major", "selection_reason": "Major.", "viewer_payoff": "Useful.", "confidence": 0.85},
                {"story_id": "candidate_005", "role": "brief", "selection_reason": "Adds a distinct payoff.", "viewer_payoff": "More variety.", "confidence": 0.88},
            ],
            "non_selected": [
                {"story_id": "candidate_003", "action": "reserve", "reason": "Less varied.", "confidence": 0.7},
                {"story_id": "candidate_004", "action": "reserve", "reason": "Alternate.", "confidence": 0.7},
            ],
            "human_review_warning": "",
            "review_changed": True,
            "review_reason": "The recovery candidate improves episode variety.",
            "diversity_assessment": "strong",
            "diversity_reason": "The stories now offer distinct mechanisms and stakes.",
            "duplicate_story_groups": [],
        }
    )

    class FakeLLM:
        def with_structured_output(self, output_model, include_raw):
            assert include_raw is True
            parsed = (
                selector_draft
                if output_model is RoundupSlateDraft
                else reviewer_draft
            )
            return RunnableLambda(
                lambda _prompt: {"parsed": parsed, "raw": None, "parsing_error": None}
            )

    monkeypatch.setattr(selection_app, "_screen_candidate_pool", fake_screen_candidate_pool)
    monkeypatch.setattr(selection_app, "make_llm", lambda **_kwargs: FakeLLM())
    result = selection_app.run(
        {
            "run": {"run_id": "recovery_fixture"},
            "config": {
                "provider": "openai",
                "model": "fixture",
                "prompt_version": "v1",
                "min_stories": 3,
                "max_stories": 3,
                "max_candidate_stories": 10,
                "screening_shortlist_per_batch": 5,
                "target_finalist_stories": 4,
                "max_attempts": 2,
                "channel": {"channel_name": "Fixture AI"},
                "slate_review": {
                    "enabled": True,
                    "prompt_version": "v1",
                    "max_attempts": 2,
                    "recovery_candidate_count": 1,
                },
            },
            "input": {
                "story_mapping": {
                    "status": "ok",
                    "data": {"run_id": "recovery_fixture", "stories": stories},
                }
            },
        }
    )

    slate = result["data"]["editorial_slate"]
    assert result["status"] == "ok"
    assert slate["selected_story_ids"] == ["story_1", "story_2", "story_5"]
    assert result["summary"]["slate_review_recovery_story_ids"] == ["story_5"]
    assert result["summary"]["slate_diversity_assessment"] == "strong"
    assert len(slate["decision_ledger"]) == len(stories)
    assert {item["story_id"] for item in slate["decision_ledger"]} == {
        story["story_id"] for story in stories
    }
