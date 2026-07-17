from __future__ import annotations

from langchain_core.runnables import RunnableLambda
import numpy as np

from src.pipeline.apps.editorial_selection.formats.roundup import app as selection_app
from src.pipeline.apps.editorial_selection.formats.roundup.contract import (
    RoundupSlateDraft,
    RoundupSlateReviewDraft,
)
from src.pipeline.apps.story_mapping.clusterer import cluster_records
from src.pipeline.apps.story_mapping.cluster_reconciler import (
    ComponentReconciliationOutput,
    reconcile_components,
)
from src.pipeline.apps.story_mapping.event_identity import (
    EventIdentityOutput,
    attach_event_identities,
)
from src.pipeline.apps.story_mapping.pair_adjudicator import (
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
            "event_action": "announced",
            "event_type": "announcement",
            "event_status": "announced",
            "event_date": "2026-07-17",
            "canonical_event": "Moonshot AI announces Kimi K3",
            "story_family": "Kimi K3 release cycle",
            "distinguishing_details": ["Weights were promised for later"],
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


def test_cluster_reconciler_reads_complete_component_and_returns_partition() -> None:
    marker = "COMPONENT_FULL_CONTEXT_MARKER"
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
                "records": [
                    {"record_key": "record_a", "semantic_content": marker},
                    {"record_key": "record_b", "semantic_content": "Same release."},
                    {"record_key": "record_c", "semantic_content": "Other article."},
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


def test_cluster_reconciliation_splits_unrelated_record_from_event_component() -> None:
    records = [
        {
            "record_key": record_key,
            "source": "fixture",
            "source_group": "tech_news_apis",
            "title": title,
            "url": f"https://example.com/{record_key}",
            "published_at": f"2026-07-17T0{index}:00:00Z",
            "content": title,
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
            parsed = (
                selector_draft
                if output_model is RoundupSlateDraft
                else reviewer_draft
            )
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
