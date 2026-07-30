from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import time

from fastapi.testclient import TestClient

from ui.controller.app.main import create_app, project_root_from_env


FAKE_RUNNER = """
from __future__ import annotations
import json
from pathlib import Path
import sys
import time

if "--help" in sys.argv:
    print("collect content voiceover visuals")
    raise SystemExit(0)

stage = sys.argv[1]
def argument(name, default=""):
    try:
        return sys.argv[sys.argv.index(name) + 1]
    except (ValueError, IndexError):
        return default

root = Path.cwd()
run_id = argument("--run-id")
if (root / "slow_runner").exists():
    for index in range(200):
        print(f"working {index}", flush=True)
        time.sleep(0.05)
if stage == "collect":
    run = root / "output" / "runs" / run_id
    (run / "orchestration").mkdir(parents=True, exist_ok=True)
    (run / "run_context.json").write_text(json.dumps({
        "run_id": run_id,
        "run_profile": argument("--profile"),
        "config_environment": argument("--environment"),
    }))
    (root / "output" / "current_run.json").write_text(json.dumps({"run_id": run_id}))
print(json.dumps({"status": "ok", "data": {"stage": stage, "run_id": run_id}}), flush=True)
"""


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    config = root / "src" / "pipeline" / "config"
    write(
        config / "workbench.yaml",
        """
config_schema_version: pipeline_modular_config_v1
default_run_profile: fixture
default_environment: dev
environments:
  dev: environments/dev.yaml
  prod: environments/prod.yaml
profiles:
  fixture:
    profile_file: profiles/fixture/profile.yaml
    stages: {}
""".lstrip(),
    )
    write(config / "environments" / "dev.yaml", "shared: {}\nmodules: {}\n")
    write(config / "environments" / "prod.yaml", "shared: {}\nmodules: {}\n")
    write(config / "profiles" / "fixture" / "profile.yaml", "channel:\n  name: Fixture\n")
    write(root / "fake_runner.py", FAKE_RUNNER)
    (root / "output" / "runs").mkdir(parents=True)
    return root


def validator(_: Path) -> dict[str, object]:
    return {
        "status": "ok",
        "profiles": ["fixture"],
        "environments": ["dev", "prod"],
        "documents": [{"profile": "fixture", "environment": "dev"}],
    }


def client_for(root: Path) -> TestClient:
    return TestClient(
        create_app(
            root,
            state_root=root / "controller-state",
            pipeline_python=sys.executable,
            runner_module="fake_runner",
            config_validator=validator,
        )
    )


def test_default_project_root_is_repository_root(monkeypatch) -> None:
    monkeypatch.delenv("RUN_DESK_PROJECT_ROOT", raising=False)
    expected = Path(__file__).resolve().parents[3]
    assert project_root_from_env() == expected


def wait_for_job(client: TestClient, job_id: str, timeout: float = 8) -> dict[str, object]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = client.get(f"/control/jobs/{job_id}").json()
        if payload["job"]["status"] not in {"queued", "running", "cancelling"}:
            return payload
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def seed_run(root: Path, run_id: str = "run_existing", *, stage_status: dict | None = None) -> None:
    run = root / "output" / "runs" / run_id
    write(
        run / "run_context.json",
        json.dumps({
            "run_id": run_id,
            "run_profile": "fixture",
            "config_environment": "dev",
        }),
    )
    status = stage_status or {"ingestion": "ok", "content": "ok", "voiceover": "ok", "visuals": "ok"}
    write(
        run / "orchestration" / "run_state.json",
        json.dumps({
            "run_id": run_id,
            "stages": {name: {"status": value} for name, value in status.items()},
        }),
    )


def test_capabilities_and_preview_use_only_canonical_arguments(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    with client_for(root) as client:
        capabilities = client.get("/control/capabilities")
        assert capabilities.status_code == 200
        data = capabilities.json()
        assert data["runtime"]["ready"] is True
        assert data["profiles"] == ["fixture"]
        assert [stage["key"] for stage in data["stages"]] == [
            "collect",
            "content",
            "voiceover",
            "visuals",
        ]

        preview = client.post(
            "/control/plans/preview",
            json={
                "operation": "new",
                "target_stage": "visuals",
                "profile": "fixture",
                "environment": "dev",
                "synthesis_mode": "preview",
            },
        )
        assert preview.status_code == 200
        plan = preview.json()
        assert [command["stage"] for command in plan["commands"]] == [
            "collect",
            "content",
            "voiceover",
            "visuals",
        ]
        assert all("--project-root" not in command["display"] for command in plan["commands"])
        assert plan["requires_provider_confirmation"] is True
        # A full episode render (no --skip-render) is heavy final-media generation.
        assert plan["requires_final_confirmation"] is True


def test_new_pipeline_job_is_idempotent_and_completes(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    with client_for(root) as client:
        request = {
            "request_id": "request_fixture_1",
            "plan": {
                "operation": "new",
                "run_id": "run_fixture",
                "target_stage": "content",
                "profile": "fixture",
                "environment": "dev",
                "confirm_provider_costs": True,
            },
        }
        first = client.post("/control/jobs", json=request)
        assert first.status_code == 200
        job_id = first.json()["job"]["id"]
        duplicate = client.post("/control/jobs", json=request)
        assert duplicate.status_code == 200
        assert duplicate.json()["job"]["id"] == job_id

        completed = wait_for_job(client, job_id)
        assert completed["job"]["status"] == "completed"
        assert completed["job"]["step_count"] == 2
        assert (root / "output" / "runs" / "run_fixture" / "run_context.json").is_file()
        lines = [event["line"] for event in completed["events"]]
        assert any("Plan completed" in line for line in lines)


def test_provider_and_final_confirmations_are_enforced(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    with client_for(root) as client:
        paid = client.post(
            "/control/jobs",
            json={
                "request_id": "request_paid",
                "plan": {
                    "operation": "new",
                    "run_id": "run_paid",
                    "profile": "fixture",
                    "environment": "dev",
                    "target_stage": "content",
                },
            },
        )
        assert paid.status_code == 409
        assert "provider costs" in paid.json()["detail"]

        final_media = client.post(
            "/control/jobs",
            json={
                "request_id": "request_final",
                "plan": {
                    "operation": "new",
                    "run_id": "run_final",
                    "profile": "fixture",
                    "environment": "dev",
                    "target_stage": "voiceover",
                    "synthesis_mode": "final",
                    "confirm_provider_costs": True,
                },
            },
        )
        assert final_media.status_code == 409
        assert "final-media" in final_media.json()["detail"]


def test_resume_boundaries_are_validated_and_command_is_scoped(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    seed_run(root)
    with client_for(root) as client:
        invalid = client.post(
            "/control/plans/preview",
            json={
                "operation": "retry",
                "run_id": "run_existing",
                "target_stage": "content",
                "from_module": "script_generation",
                "stop_after": "story_mapping",
            },
        )
        assert invalid.status_code == 400

        valid = client.post(
            "/control/plans/preview",
            json={
                "operation": "retry",
                "run_id": "run_existing",
                "target_stage": "content",
                "from_module": "story_mapping",
                "stop_after": "script_generation",
            },
        )
        assert valid.status_code == 200
        command = valid.json()["commands"][0]["display"]
        assert "--from-module story_mapping" in command
        assert "--stop-after script_generation" in command

        # The visuals stage no longer supports module boundaries; it takes the
        # motion-graphics engine flags instead.
        visuals = client.post(
            "/control/plans/preview",
            json={
                "operation": "retry",
                "run_id": "run_existing",
                "target_stage": "visuals",
                "deterministic": True,
                "units": 2,
                "skip_render": True,
            },
        )
        assert visuals.status_code == 200
        visuals_command = visuals.json()["commands"][0]["display"]
        assert "--deterministic" in visuals_command
        assert "--units 2" in visuals_command
        assert "--skip-render" in visuals_command


def test_resume_can_run_through_a_later_stage(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    seed_run(root)
    with client_for(root) as client:
        chained = client.post(
            "/control/plans/preview",
            json={
                "operation": "resume",
                "run_id": "run_existing",
                "target_stage": "voiceover",
                "run_to_stage": "visuals",
                "synthesis_mode": "preview",
            },
        )
        assert chained.status_code == 200
        assert [command["stage"] for command in chained.json()["commands"]] == ["voiceover", "visuals"]

        backwards = client.post(
            "/control/plans/preview",
            json={
                "operation": "resume",
                "run_id": "run_existing",
                "target_stage": "visuals",
                "run_to_stage": "voiceover",
            },
        )
        assert backwards.status_code == 400


def test_resume_is_gated_by_persisted_run_state(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    # Content complete, voiceover failed, visuals untouched: visuals is not runnable.
    seed_run(root, stage_status={"ingestion": "ok", "content": "ok", "voiceover": "failed"})
    with client_for(root) as client:
        status = client.get("/control/runs/run_existing/status")
        assert status.status_code == 200
        payload = status.json()
        assert payload["next_stage"] == "voiceover"
        runnable = {stage["key"]: stage["runnable"] for stage in payload["stages"]}
        assert runnable == {"collect": True, "content": True, "voiceover": True, "visuals": False}

        # Voiceover can be resumed (its content input exists).
        ok = client.post(
            "/control/plans/preview",
            json={"operation": "resume", "run_id": "run_existing", "target_stage": "voiceover"},
        )
        assert ok.status_code == 200

        # Visuals cannot: voiceover has not completed, so its input is missing.
        blocked = client.post(
            "/control/plans/preview",
            json={"operation": "resume", "run_id": "run_existing", "target_stage": "visuals"},
        )
        assert blocked.status_code == 400
        assert "voiceover" in blocked.json()["detail"]

        missing = client.get("/control/runs/run_missing/status")
        assert missing.status_code == 404


def test_running_job_can_be_cancelled_and_blocks_another_writer(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    seed_run(root)
    (root / "slow_runner").touch()
    with client_for(root) as client:
        first = client.post(
            "/control/jobs",
            json={
                "request_id": "request_slow",
                "plan": {
                    "operation": "resume",
                    "run_id": "run_existing",
                    "target_stage": "collect",
                },
            },
        )
        assert first.status_code == 200
        job_id = first.json()["job"]["id"]
        deadline = time.time() + 3
        while time.time() < deadline:
            job = client.get(f"/control/jobs/{job_id}").json()["job"]
            if job["status"] == "running":
                break
            time.sleep(0.02)

        second = client.post(
            "/control/jobs",
            json={
                "request_id": "request_second",
                "plan": {
                    "operation": "resume",
                    "run_id": "run_existing",
                    "target_stage": "collect",
                },
            },
        )
        assert second.status_code == 409

        cancelled = client.post(f"/control/jobs/{job_id}/cancel")
        assert cancelled.status_code == 200
        finished = wait_for_job(client, job_id)
        assert finished["job"]["status"] == "cancelled"


def test_config_edit_is_atomic_validated_and_conflict_aware(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    with client_for(root) as client:
        traversal = client.get("/control/config/file", params={"path": "../outside.yaml"})
        assert traversal.status_code == 400

        outside = root / "outside.yaml"
        write(outside, "outside: true\n")
        (root / "src" / "pipeline" / "config" / "escape.yaml").symlink_to(outside)
        escaped = client.get("/control/config/file", params={"path": "escape.yaml"})
        assert escaped.status_code == 400
        assert all(
            file["path"] != "escape.yaml"
            for file in client.get("/control/config/files").json()["files"]
        )
        (root / "src" / "pipeline" / "config" / "escape.yaml").unlink()

        opened = client.get(
            "/control/config/file",
            params={"path": "profiles/fixture/profile.yaml"},
        )
        assert opened.status_code == 200
        before = opened.json()
        updated_text = "channel:\n  name: Updated Fixture\n"
        saved = client.put(
            "/control/config/file",
            json={
                "path": before["path"],
                "expected_sha256": before["sha256"],
                "text": updated_text,
                "change_summary": "Update fixture channel name",
                "confirm_write": True,
            },
        )
        assert saved.status_code == 200
        assert saved.json()["validation"]["status"] == "ok"
        assert (root / "src" / "pipeline" / "config" / before["path"]).read_text() == updated_text

        stale = client.put(
            "/control/config/file",
            json={
                "path": before["path"],
                "expected_sha256": before["sha256"],
                "text": "channel:\n  name: Stale\n",
                "change_summary": "Attempt stale update",
                "confirm_write": True,
            },
        )
        assert stale.status_code == 409

        current = saved.json()
        secret = client.put(
            "/control/config/file",
            json={
                "path": before["path"],
                "expected_sha256": current["sha256"],
                "text": "channel:\n  api_key: exposed-value\n",
                "change_summary": "Attempt unsafe value",
                "confirm_write": True,
            },
        )
        assert secret.status_code == 400
        assert "Credentials must remain" in secret.json()["detail"]


def test_review_notes_are_ui_owned_and_run_scoped(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    seed_run(root)
    with client_for(root) as client:
        saved = client.put(
            "/control/notes/run_existing",
            json={"status": "needs_changes", "body": "Recheck the lead scene."},
        )
        assert saved.status_code == 200
        assert saved.json()["status"] == "needs_changes"
        assert client.get("/control/notes/run_existing").json()["body"] == "Recheck the lead scene."
        assert not (root / "output" / "runs" / "run_existing" / "review_notes.json").exists()

        missing = client.get("/control/notes/run_missing")
        assert missing.status_code == 404
