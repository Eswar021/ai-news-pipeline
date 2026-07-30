from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.repository import RepositoryError, SafeRepository


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    config = root / "src" / "pipeline" / "config"
    runs = root / "output" / "runs"
    config.mkdir(parents=True)
    runs.mkdir(parents=True)
    write_text(config / "workbench.yaml", "profiles:\n  daily: {}\n")
    write_text(config / "profiles" / "daily" / "content" / "script_generation.yaml", "model: fixture\n")
    write_json(root / "output" / "current_run.json", {"run_id": "run_good"})

    good = runs / "run_good"
    write_json(good / "run_context.json", {
        "run_id": "run_good",
        "created_at": "2026-07-22T00:00:00Z",
        "run_profile": "daily",
        "config_environment": "dev",
        "trigger": "fixture",
        "profile_config": {"script_generation": {"provider": "openai", "model": "gpt-4o"}},
    })
    write_json(good / "orchestration" / "run_state.json", {
        "run_id": "run_good",
        "run_profile": "daily",
        "stages": {
            "content": {
                "status": "ok",
                "modules": {
                    "script_generation": {
                        "status": "ok",
                        "reused": False,
                        "summary": {"total_word_count": 42},
                    }
                },
            },
            "voiceover": {"status": "partial", "modules": {"voiceover": {"status": "ok"}}},
        },
    })
    write_json(good / "script_generation" / "summary.json", {"status": "ok", "total_word_count": 42})
    write_json(good / "script_generation" / "script_package.json", {
        "full_script": "Hello world",
        "sections": [{"section_id": "section_00_intro", "word_count": 2, "beats": [{"beat_id": "b1", "text": "Hello world"}]}],
    })
    write_json(good / "script_generation" / "config_snapshot.json", {"route": {"provider": "openai", "model": "gpt-4o"}})
    write_text(good / "script_generation" / "llm_calls.jsonl", json.dumps({
        "module_name": "writer",
        "provider": "openai",
        "model": "gpt-4o",
        "status": "ok",
        "messages": [{"role": "user", "content": "complete prompt"}],
        "raw_response": {"text": "raw"},
        "parsing_diagnostics": {"ok": True},
    }) + "\n")
    write_text(good / "orchestration" / "logs" / "content.log", "INFO start\nWARNING partial\nERROR none\n")
    final_video = good / "visuals" / "run_good-ad.mp4"
    final_video.parent.mkdir(parents=True, exist_ok=True)
    final_video.write_bytes(b"fixture-mp4-data")
    write_json(good / "orchestration" / "visuals_stage_result.json", {
        "status": "ok",
        "data": {
            "run_id": "run_good",
            "stage": "visuals",
            "episode_path": "output/runs/run_good/visuals/run_good-ad.mp4",
            "visuals_dir": "output/runs/run_good/visuals",
        },
        "summary": {"engine": "video_engine/scripts/pipeline/render-episode.mjs", "art_director": "llm", "units": None, "rendered": True},
        "handoff": {"episode_rendered": True},
    })

    for variant in ["variant_a", "variant_b"]:
        base = good / "voiceover" / variant
        write_json(base / "summary.json", {"provider": "fixture", "voice": variant, "duration_seconds": 1.0})
        write_json(base / "voiceover_package.json", {
            "status": "ready",
            "provider": "fixture",
            "voice": variant,
            "audio": {"full_audio_path": f"output/runs/run_good/voiceover/{variant}/audio/full_voiceover.wav", "duration_seconds": 1.0},
            "audio_units": [{"audio_unit_id": "u1", "section_id": "s1", "start_seconds": 0, "end_seconds": 1}],
            "chunks": [],
        })
        (base / "audio").mkdir(parents=True, exist_ok=True)
        (base / "audio" / "full_voiceover.wav").write_bytes(b"0123456789abcdef")
        write_text(base / "tts_requests.jsonl", json.dumps({"request_id": "tts_1", "status": "succeeded", "transcript": "hello"}) + "\n")

    partial = runs / "run_partial"
    partial.mkdir()
    write_json(partial / "run_context.json", {"run_id": "run_partial", "run_profile": "daily"})

    malformed = runs / "run_malformed"
    malformed.mkdir()
    write_text(malformed / "run_context.json", "{not-json")
    return root


def client_for(root: Path) -> TestClient:
    return TestClient(create_app(root))


def seed_record_lineage(root: Path) -> None:
    run = root / "output" / "runs" / "run_good"
    write_json(run / "news_collection" / "raw_records.json", {
        "records": [
            {
                "record_id": "record_1",
                "candidate_key": "candidate_1",
                "title": "Fixture launch",
                "url": "https://example.com/launch",
                "source": "fixture_news",
                "source_group": "official_blogs",
                "content": "The fixture product launched with a documented API.",
            },
            {
                "record_id": "record_2",
                "candidate_key": "candidate_2",
                "title": "Fixture opinion",
                "url": "https://example.com/opinion",
                "source": "fixture_news",
                "source_group": "commentary",
                "content": "An opinion without primary evidence.",
            },
        ]
    })
    write_json(run / "evidence_prep" / "decision_ledger.json", {
        "decisions": [
            {
                "record_id": "record_1",
                "record_key": "record_1",
                "decision": "candidate",
                "reason_codes": [],
            },
            {
                "record_id": "record_2",
                "decision": "hard_reject",
                "reason_codes": ["unsupported_commentary"],
            },
        ]
    })
    write_json(run / "evidence_prep" / "prepared_records.json", {
        "records": [{
            "record_key": "record_1",
            "candidate_key": "candidate_1",
            "title": "Fixture launch",
            "url": "https://example.com/launch",
            "source": "fixture_news",
            "cleaned_content": "The fixture product launched with a documented API.",
            "content_status": "usable",
        }]
    })
    write_json(run / "editorial_triage" / "decisions.json", {
        "decisions": [{
            "record_key": "record_1",
            "recommended_action": "advance",
            "reason": "Useful product news.",
            "confidence": 0.94,
            "possible_story_keys": ["fixture_launch"],
        }]
    })
    write_json(run / "story_mapping" / "stories.json", {
        "stories": [{
            "story_id": "story_1",
            "story_title": "Fixture launch",
            "story_identity": {
                "one_sentence_story": "The fixture product launched.",
                "why_it_matters": "It gives readers a stable API.",
            },
            "records": [{
                "record_key": "record_1",
                "title": "Fixture launch",
                "url": "https://example.com/launch",
                "source": "fixture_news",
                "story_mapping_event_identity": {"entities": ["Fixture product"], "event_type": "launch"},
            }],
        }]
    })
    write_json(run / "editorial_selection" / "editorial_slate.json", {
        "selected_stories": [{
            "story_id": "story_1",
            "story_title": "Fixture launch",
            "editorial_selection": {
                "role": "lead",
                "selection_reason": "Strong lead.",
                "viewer_payoff": "A concrete release.",
            },
        }],
        "reserve_stories": [],
        "rejected": [],
    })
    write_json(run / "video_packaging" / "video_packet.json", {
        "stories": [{"story_id": "story_1", "story_title": "Fixture launch", "records": [{"record_key": "record_1"}]}]
    })
    write_json(run / "script_generation" / "script_package.json", {
        "full_script": "The fixture product has launched.",
        "sections": [{
            "section_id": "s1",
            "story_id": "story_1",
            "story_title": "Fixture launch",
            "narration_text": "The fixture product has launched.",
            "used_source_record_keys": ["record_1"],
            "beats": [{
                "beat_id": "b1",
                "narration_text": "The fixture product has launched.",
                "source_record_keys": ["record_1"],
            }],
        }],
    })
    write_json(run / "metadata_creator" / "metadata_package.json", {
        "youtube_metadata": {
            "tags": ["fixture", "product launch"],
            "source_urls": ["https://example.com/launch"],
            "title_options": [{"text": "Fixture product launches", "represented_story_ids": ["story_1"]}],
            "thumbnail_concepts": [{"headline": "Fixture Launch", "represented_story_ids": ["story_1"]}],
            "chapters": [{"section_id": "s1", "title": "Fixture launch", "start_seconds": 0}],
        }
    })
    write_json(run / "metadata_finalizer" / "metadata_package.json", {
        "youtube_metadata": {"chapters": [{"section_id": "s1", "title": "Fixture launch", "start_seconds": 0}]}
    })


def test_discovers_complete_partial_and_malformed_runs(tmp_path: Path) -> None:
    client = client_for(make_project(tmp_path))
    response = client.get("/api/runs")
    assert response.status_code == 200
    runs = {run["run_id"]: run for run in response.json()["runs"]}
    assert {"run_good", "run_partial", "run_malformed"} <= set(runs)
    assert runs["run_good"]["is_current"] is True
    assert runs["run_malformed"]["overall_status"] == "malformed"


def test_catalog_centralizes_workflow_help_and_generation_provenance(tmp_path: Path) -> None:
    client = client_for(make_project(tmp_path))
    response = client.get("/api/catalog")
    assert response.status_code == 200
    catalog = response.json()

    assert catalog["read_only"] is True
    assert [stage["key"] for stage in catalog["stages"]] == [
        "ingestion",
        "content",
        "voiceover",
        "visuals",
    ]
    assert len(catalog["modules"]) == 11
    assert catalog["help"]["raw_mode"].startswith("The exact persisted")
    assert catalog["origins"]["llm"]["label"] == "LLM-generated"
    assert "Stable evidence identity" in catalog["glossary"]["record key"]

    script = catalog["modules"]["script_generation"]
    assert script["primary_origin"] == "mixed"
    assert {output["origin"] for output in script["outputs"]} == {"llm", "deterministic"}
    assert "narration_text" in script["outputs"][0]["fields"]

    voiceover = catalog["modules"]["voiceover"]
    assert {output["origin"] for output in voiceover["outputs"]} == {"model", "deterministic"}


def test_path_security_rejects_traversal_denied_names_and_symlink_escape(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    secret_dir = root / "secrets"
    secret_dir.mkdir()
    write_text(secret_dir / "note.txt", "nope")
    (root / "output" / "runs" / "run_good" / "leak").symlink_to(secret_dir / "note.txt")
    repo = SafeRepository(root)

    for path in ["../AGENTS.md", "/tmp/nope", "output/../.env", "output/runs/run_good/.env"]:
        try:
            repo.resolve_allowlisted(path)
        except RepositoryError:
            pass
        else:
            raise AssertionError(f"expected {path} to be rejected")

    client = client_for(root)
    assert client.get("/api/media", params={"path": "output/runs/run_good/leak"}).status_code == 400


def test_artifact_viewer_handles_malformed_json_and_missing_files(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    write_text(root / "output" / "runs" / "run_good" / "bad.json", "{oops")
    client = client_for(root)

    bad = client.get("/api/runs/run_good/artifacts", params={"path": "bad.json"})
    assert bad.status_code == 200
    assert bad.json()["parse_error"].startswith("Malformed JSON")

    missing = client.get("/api/runs/run_good/artifacts", params={"path": "missing.json"})
    assert missing.status_code == 404


def test_voiceover_variants_and_tts_pagination(tmp_path: Path) -> None:
    client = client_for(make_project(tmp_path))
    variants = client.get("/api/runs/run_good/voiceovers")
    assert variants.status_code == 200
    assert len(variants.json()["voiceovers"]) == 2

    tts = client.get("/api/runs/run_good/tts-calls/variant_a")
    assert tts.status_code == 200
    assert tts.json()["total"] == 1


def test_jsonl_payload_expansion_and_range_streaming(tmp_path: Path) -> None:
    client = client_for(make_project(tmp_path))
    page = client.get("/api/runs/run_good/llm-calls/script_generation")
    assert page.status_code == 200
    row = page.json()["rows"][0]
    assert row["has_payload"] is True
    assert "messages" not in row

    detail = client.get("/api/runs/run_good/llm-calls/script_generation/records/0")
    assert detail.status_code == 200
    assert detail.json()["messages"][0]["content"] == "complete prompt"

    media = client.get(
        "/api/media",
        params={"path": "output/runs/run_good/voiceover/variant_a/audio/full_voiceover.wav"},
        headers={"Range": "bytes=0-3"},
    )
    assert media.status_code == 206
    assert media.headers["content-range"] == "bytes 0-3/16"
    assert media.content == b"0123"

    video = client.get(
        "/api/media",
        params={"path": "output/runs/run_good/visuals/run_good-ad.mp4"},
        headers={"Range": "bytes=8-10"},
    )
    assert video.status_code == 206
    assert video.headers["content-type"] == "video/mp4"
    assert video.content == b"mp4"

    logs = client.get(
        "/api/runs/run_good/logs/content",
        params={"severity": "warning"},
    )
    assert logs.status_code == 200
    assert logs.json()["lines"] == ["WARNING partial"]


def test_workflow_and_record_lineage_use_deterministic_artifacts(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    seed_record_lineage(root)
    client = client_for(root)

    workflow = client.get("/api/runs/run_good/workflow")
    assert workflow.status_code == 200
    stages = workflow.json()["stages"]
    assert [stage["key"] for stage in stages] == ["ingestion", "content", "voiceover", "visuals"]
    assert [module["name"] for module in stages[1]["modules"]] == [
        "evidence_prep",
        "editorial_triage",
        "story_mapping",
        "editorial_selection",
        "video_packaging",
        "script_generation",
        "metadata_creator",
    ]
    script_module = next(module for module in stages[1]["modules"] if module["name"] == "script_generation")
    assert script_module["primary_origin"] == "mixed"
    assert any(output["origin"] == "llm" for output in script_module["outputs"])

    records = client.get("/api/runs/run_good/records")
    assert records.status_code == 200
    assert records.json()["counts"]["selected"] == 1
    assert records.json()["counts"]["filtered"] == 1

    selected = client.get("/api/runs/run_good/records/record_1")
    assert selected.status_code == 200
    selected_steps = selected.json()["stages"]
    assert len(selected_steps) == 11
    metadata_step = next(step for step in selected_steps if step["key"] == "metadata_creator")
    assert metadata_step["status"] == "episode_level"
    assert metadata_step["data"]["article_tags_created"] is False
    assert metadata_step["data"]["source_url_included"] is True
    assert metadata_step["generation"]["primary_origin"] == "mixed"
    assert {output["origin"] for output in metadata_step["generation"]["outputs"]} == {"llm", "deterministic"}
    voice_step = next(step for step in selected_steps if step["key"] == "voiceover")
    assert voice_step["status"] == "produced"

    filtered = client.get("/api/runs/run_good/records/record_2")
    assert filtered.status_code == 200
    filtered_steps = {step["key"]: step for step in filtered.json()["stages"]}
    assert filtered_steps["evidence_prep"]["status"] == "stopped"
    assert filtered_steps["editorial_triage"]["status"] == "not_reached"


def test_curated_read_models_and_deferred_artifact_tree(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    run = root / "output" / "runs" / "run_good"
    state = json.loads((run / "orchestration" / "run_state.json").read_text(encoding="utf-8"))
    state["stages"]["ingestion"] = {
        "status": "ok",
        "modules": {"news_collection": {"status": "partial"}},
    }
    write_json(run / "orchestration" / "run_state.json", state)
    write_json(run / "news_collection" / "summary.json", {
        "status": "partial",
        "total_records": 1,
        "enabled_source_group_count": 1,
        "successful_source_group_count": 1,
        "groups": {
            "official_blogs": {
                "status": "ok",
                "collector": "fixture",
                "collected_count": 1,
                "sources": {"fixture_news": {"status": "ok", "collected_count": 1, "notes": []}},
            }
        },
    })
    write_json(run / "news_collection" / "raw_records.json", {
        "records": [{
            "record_id": "record_1",
            "title": "Fixture launch",
            "url": "https://example.com/launch",
            "source": "fixture_news",
            "source_group": "official_blogs",
            "content": "A long source body that should not be copied into the compact read model.",
            "summary": "A concise launch summary.",
        }]
    })
    write_json(run / "evidence_prep" / "prepared_records.json", {
        "records": [{"record_key": "record_1", "title": "Fixture launch", "source": "fixture_news", "url": "https://example.com/launch"}]
    })
    write_json(run / "evidence_prep" / "summary.json", {
        "input_record_count": 1,
        "prepared_record_count": 1,
    })
    write_json(run / "editorial_triage" / "summary.json", {"decision_count": 1, "action_counts": {"advance": 1}})
    write_json(run / "editorial_triage" / "decisions.json", {
        "decisions": [{"record_key": "record_1", "recommended_action": "advance", "reason": "Useful to the audience.", "confidence": 0.9}]
    })
    write_json(run / "story_mapping" / "stories.json", {
        "stories": [{
            "story_id": "story_1",
            "story_title": "Fixture launch",
            "story_identity": {"one_sentence_story": "A fixture launched.", "why_it_matters": "It proves the reader."},
            "records": [{"record_key": "record_1", "title": "Fixture launch", "source": "fixture_news", "url": "https://example.com/launch"}],
        }]
    })
    write_json(run / "editorial_selection" / "editorial_slate.json", {
        "selected_stories": [{
            "story_id": "story_1",
            "story_title": "Fixture launch",
            "story_identity": {"one_sentence_story": "A fixture launched."},
            "editorial_selection": {"role": "lead", "selection_reason": "Strong lead.", "viewer_payoff": "Clear value."},
            "records": [],
        }],
        "reserve_stories": [],
        "rejected": [],
    })
    write_json(run / "editorial_selection" / "summary.json", {
        "selected_story_count": 1,
    })

    client = client_for(root)
    detail = client.get("/api/runs/run_good").json()
    assert detail["artifact_tree"] == []
    assert detail["artifact_tree_deferred"] is True
    assert detail["index"]["metrics"]["collected_record_count"] == 1
    assert detail["index"]["metrics"]["prepared_record_count"] == 1
    assert detail["index"]["metrics"]["selected_story_count"] == 1

    tree = client.get("/api/runs/run_good/artifact-tree")
    assert tree.status_code == 200
    assert tree.json()["tree"]

    collection_detail = client.get("/api/runs/run_good/modules/news_collection").json()
    assert collection_detail["status"] == "partial"
    collection = collection_detail["curated"]
    assert collection["records"][0]["title"] == "Fixture launch"
    assert collection["records"][0]["excerpt"] == "A concise launch summary."
    assert "content" not in collection["records"][0]

    triage = client.get("/api/runs/run_good/modules/editorial_triage").json()["curated"]
    assert triage["decisions"][0]["title"] == "Fixture launch"
    assert triage["decisions"][0]["recommended_action"] == "advance"

    selection = client.get("/api/runs/run_good/modules/editorial_selection").json()["curated"]
    assert selection["selected_stories"][0]["role"] == "lead"
    assert selection["selected_stories"][0]["selection_reason"] == "Strong lead."

    script_detail = client.get("/api/runs/run_good/modules/script_generation").json()
    assert script_detail["generation_evidence"]["llm_ledger_persisted"] is True
    assert script_detail["generation_evidence"]["classification_source"] == "inspector_catalog"


def test_run_comparison_and_contextual_llm_provenance(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    seed_record_lineage(root)
    runs = root / "output" / "runs"
    compare = runs / "run_compare"
    write_json(compare / "run_context.json", {
        "run_id": "run_compare",
        "created_at": "2026-07-23T00:00:00Z",
        "run_profile": "daily",
        "config_environment": "dev",
        "profile_config": {"script_generation": {"provider": "fixture", "model": "comparison"}},
    })
    write_json(compare / "orchestration" / "run_state.json", {
        "run_id": "run_compare",
        "stages": {
            "content": {
                "status": "ok",
                "modules": {
                    "script_generation": {"status": "ok", "summary": {"total_word_count": 6}},
                    "metadata_creator": {"status": "ok"},
                },
            }
        },
    })
    write_json(compare / "script_generation" / "script_package.json", {
        "full_script": "A different fixture script with six words.",
        "sections": [{
            "section_id": "s1",
            "story_id": "story_1",
            "story_title": "Fixture comparison",
            "narration_text": "A different fixture script with six words.",
            "word_count": 7,
        }],
        "provenance": {"content_fingerprint": "comparison-fingerprint"},
    })
    write_json(compare / "metadata_creator" / "metadata_package.json", {
        "youtube_metadata": {
            "title_options": [{"text": "A comparison title"}],
            "tags": ["comparison"],
            "chapters": [{"section_id": "s1", "title": "Comparison", "start_seconds": 0}],
        }
    })
    write_text(compare / "script_generation" / "llm_calls.jsonl", json.dumps({
        "module_name": "roundup_story_writer",
        "provider": "fixture",
        "model": "comparison",
        "duration_seconds": 1.25,
        "usage": {"prompt_tokens": 10, "completion_tokens": 6, "total_tokens": 16},
        "metadata": {
            "story_id": "story_1",
            "source_record_keys": ["record_1"],
            "section_id": "s1",
        },
        "messages": [{"role": "user", "content": "fixture prompt"}],
        "response_text": "fixture response",
    }) + "\n")

    client = client_for(root)
    response = client.get("/api/compare/runs", params={"left": "run_good", "right": "run_compare"})
    assert response.status_code == 200
    comparison = response.json()
    assert comparison["script"]["changed"] is True
    assert comparison["script"]["sections"][0]["section_id"] == "s1"
    assert comparison["metadata"]["fields"][0]["changed"] is True
    assert comparison["usage"]["right"]["llm"]["total_tokens"] == 16
    assert "do not currently contain currency cost" in comparison["usage"]["cost_note"]

    provenance = client.get(
        "/api/runs/run_compare/provenance/llm/script_generation",
        params={"record_key": "record_1", "story_id": "story_1", "section_id": "s1"},
    )
    assert provenance.status_code == 200
    payload = provenance.json()
    assert payload["precision"] == "contextual"
    assert payload["matches"][0]["index"] == 0
    assert len(payload["matches"][0]["match_reasons"]) == 3
