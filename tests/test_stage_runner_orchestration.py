from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from src.pipeline.orchestration import runner
from src.pipeline.orchestration.logging import configure_stage_logging
from src.pipeline.orchestration.stages.content import _validate_news_collection_credentials
from src.pipeline.orchestration.state import RunStateStore


def _run_context(tmp_path: Path) -> dict:
    run_dir = tmp_path / "output" / "runs" / "run_test"
    run_dir.mkdir(parents=True)
    return {
        "run_id": "run_test",
        "run_profile": "fixture",
        "run_dir": str(run_dir),
        "profile_config": {},
    }


def test_stage_logger_writes_readable_and_structured_logs(tmp_path: Path) -> None:
    context = _run_context(tmp_path)
    stage_logger = configure_stage_logging(
        context,
        "content",
        {
            "console_enabled": False,
            "file_enabled": True,
            "profile": "summary",
            "dependency_levels": {"httpx": "WARNING"},
        },
    )

    result = stage_logger.run_module(
        "fixture_module",
        lambda payload: {
            "status": "ok",
            "data": payload,
            "summary": {"record_count": 3},
            "handoff": {},
        },
        {"value": 1},
    )

    logs_dir = Path(context["run_dir"]) / "orchestration" / "logs"
    readable = (logs_dir / "content.log").read_text(encoding="utf-8")
    events = [json.loads(line) for line in (logs_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert result["status"] == "ok"
    assert "START module=fixture_module" in readable
    assert "END module=fixture_module status=ok" in readable
    assert 'summary={"record_count":3}' in readable
    assert [event["event"] for event in events][-2:] == ["module.started", "module.completed"]
    assert events[-1]["details"] == {"record_count": 3}
    assert stage_logger.log_path == logs_dir / "content.log"
    assert logging.getLogger("httpx").level == logging.WARNING

    response = stage_logger.attach_paths(
        {"status": "ok", "data": {}, "summary": {}, "handoff": {}},
        state_path=logs_dir.parent / "run_state.json",
    )
    assert response["data"] == {
        "log_path": str(logs_dir / "content.log"),
        "events_path": str(logs_dir / "events.jsonl"),
        "run_state_path": str(logs_dir.parent / "run_state.json"),
    }

    logging.getLogger("ai_content_creation.runtime.visual_render").info(
        "RENDER progress completed=1/2"
    )
    readable = (logs_dir / "content.log").read_text(encoding="utf-8")
    assert "RENDER progress completed=1/2" in readable


def test_run_state_tracks_reused_modules_and_stage_completion(tmp_path: Path) -> None:
    context = _run_context(tmp_path)
    state = RunStateStore(context)
    state.start_stage("content", ["news_collection", "evidence_prep"])
    state.record_module(
        "content",
        "news_collection",
        status="ok",
        result_path="news_collection_result.json",
        summary={"record_count": 5},
        reused=True,
    )
    state.finish_stage("content", status="ok")

    stored = state.read()
    assert stored["stages"]["content"]["status"] == "ok"
    assert stored["stages"]["content"]["modules"]["news_collection"]["reused"] is True
    assert stored["stages"]["content"]["modules"]["news_collection"]["summary"]["record_count"] == 5


def test_runner_builds_voiceover_envelope_and_accepts_config_overrides(monkeypatch, capsys) -> None:
    captured: dict = {}

    def fake_stage(request: dict) -> dict:
        captured.update(request)
        return {
            "status": "ok",
            "data": {"run_id": request["run"]["run_id"]},
            "summary": {"provider": "fixture"},
            "handoff": {"ready_for_visuals": True},
        }

    monkeypatch.setattr(runner, "_stage_function", lambda _stage: fake_stage)
    exit_code = runner.main(
        [
            "voiceover",
            "--run-id",
            "run_test",
            "--script-source",
            "app",
            "--config-overrides-json",
            '{"voice":"af_heart","speed":1.05}',
        ]
    )

    console = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert captured["run"]["run_id"] == "run_test"
    assert captured["config"]["script_source"] == "app"
    assert captured["input"]["voiceover_config_overrides"] == {
        "voice": "af_heart",
        "speed": 1.05,
    }
    assert console["handoff"]["ready_for_visuals"] is True


def test_runner_returns_a_structured_cli_failure(monkeypatch, capsys) -> None:
    def fail_stage(_request: dict) -> dict:
        raise ValueError("bad fixture request")

    monkeypatch.setattr(runner, "_stage_function", lambda _stage: fail_stage)
    exit_code = runner.main(["content", "--profile", "fixture"])
    console = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert console["status"] == "failed"
    assert console["summary"]["failure_reason"] == "ValueError: bad fixture request"


def test_runner_rejects_specialized_voiceover_environment(monkeypatch, capsys) -> None:
    monkeypatch.setenv("VIRTUAL_ENV", "/project/.venv-voiceover")
    monkeypatch.setattr(
        runner,
        "_stage_function",
        lambda _stage: (_ for _ in ()).throw(AssertionError("stage import should not run")),
    )

    exit_code = runner.main(["content", "--profile", "fixture"])
    console = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert console["status"] == "failed"
    assert "must use the main project Python" in console["summary"]["failure_reason"]
    assert "launches .venv-voiceover internally" in console["summary"]["failure_reason"]


def test_runner_loads_project_dotenv_before_stage_import(monkeypatch, tmp_path: Path, capsys) -> None:
    secret_name = "PIPELINE_RUNNER_FIXTURE_SECRET"
    monkeypatch.delenv(secret_name, raising=False)
    (tmp_path / ".env").write_text(f"{secret_name} = loaded\n", encoding="utf-8")

    def fake_stage(_request: dict) -> dict:
        return {
            "status": "ok",
            "data": {"secret_loaded": os.getenv(secret_name)},
            "summary": {},
            "handoff": {},
        }

    monkeypatch.setattr(runner, "_stage_function", lambda _stage: fake_stage)
    exit_code = runner.main(
        ["content", "--profile", "fixture", "--project-root", str(tmp_path)]
    )
    console = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert console["data"]["secret_loaded"] == "loaded"


def test_news_credential_preflight_reports_all_enabled_missing_sources(monkeypatch) -> None:
    for key in ("NEWS_FIXTURE_A", "NEWS_FIXTURE_B", "YOUTUBE_FIXTURE_KEY"):
        monkeypatch.delenv(key, raising=False)
    payload = {
        "config": {
            "enabled_source_groups": ["tech_news", "youtube"],
            "collectors": {
                "tech_news": {
                    "sources": [
                        {
                            "id": "provider_a",
                            "enabled": True,
                            "env_keys": ["NEWS_FIXTURE_A", "NEWS_FIXTURE_B"],
                        },
                        {
                            "id": "disabled_provider",
                            "enabled": False,
                            "env_keys": ["IGNORED_FIXTURE_KEY"],
                        },
                    ]
                },
                "youtube": {"env_keys": ["YOUTUBE_FIXTURE_KEY"]},
            },
        }
    }

    try:
        _validate_news_collection_credentials(payload)
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("missing enabled credentials should fail preflight")

    assert "tech_news.provider_a (NEWS_FIXTURE_A | NEWS_FIXTURE_B)" in message
    assert "youtube (YOUTUBE_FIXTURE_KEY)" in message
    assert "disabled_provider" not in message
