from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from src.pipeline.visuals.render import app as render_app
from src.pipeline.visuals.render.contract import VisualRenderConfig, VisualRenderRequest
from src.pipeline.visuals.assembly.app import _preflight_failure_reason


def _request(tmp_path: Path, **config_overrides: object) -> VisualRenderRequest:
    config = {
        "output_dir": str(tmp_path / "render"),
        "worker_count": 3,
        "frame_concurrency": 2,
        "max_render_attempts": 2,
        "keep_render_logs": True,
        **config_overrides,
    }
    return VisualRenderRequest.model_validate(
        {
            "run": {"run_id": "render_test"},
            "config": config,
            "input": {
                "visual_asset_resolution": {
                    "status": "ok",
                    "data": {
                        "run_id": "render_test",
                        "visual_asset_manifest": {
                            "render_scenes": [
                                {
                                    "scene_id": "scene_001",
                                    "scene_order": 1,
                                    "render_kind": "kinetic_type_scene",
                                    "duration_seconds": 5,
                                }
                            ]
                        }
                    },
                }
            },
        }
    )


def test_render_config_bounds_attempts() -> None:
    with pytest.raises(ValueError, match="must not exceed 5"):
        VisualRenderConfig(output_dir="render", max_render_attempts=6)


def test_scene_render_retries_once_and_keeps_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request(tmp_path)
    scene = {
        "scene_id": "scene_001",
        "scene_order": 1,
        "render_kind": "kinetic_type_scene",
        "duration_seconds": 5,
    }
    spec_path = tmp_path / "scene_001.json"
    output_path = tmp_path / "scene_001.mp4"
    spec_path.write_text("{}", encoding="utf-8")
    calls = 0

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(args=["npm"], returncode=0, stdout=f"attempt {calls}", stderr="")

    def valid_after_retry(path: Path) -> bool:
        return calls >= 2 and path == output_path

    monkeypatch.setattr(render_app.subprocess, "run", fake_run)
    monkeypatch.setattr(render_app, "_is_valid_rendered_video", valid_after_retry)

    result = render_app._render_prepared_scene(
        job={
            "index": 0,
            "scene": scene,
            "spec": {"duration_seconds": 5},
            "spec_path": spec_path,
            "output_path": output_path,
        },
        engine_dir=tmp_path,
        bundle_dir=tmp_path / "bundle",
        logs_dir=tmp_path / "logs",
        request=request,
    )

    assert result["status"] == "rendered"
    assert result["attempt_count"] == 2
    assert result["warning"] == "Rendered successfully on retry attempt 2."
    assert len(result["log_paths"]) == 2
    assert calls == 2


def test_shared_bundle_prepares_broll_asset_once(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fixture-video")
    public_dir = tmp_path / "public"
    public_dir.mkdir()
    spec = {
        "scene": {
            "scene_id": "scene_007",
            "resolved_asset": {
                "asset_type": "broll_video",
                "asset_path": str(source),
            },
        }
    }

    render_app._prepare_shared_runtime_asset(spec, public_dir)

    asset = spec["scene"]["resolved_asset"]
    assert asset["asset_public_path"] == "scene_007.mp4"
    assert (public_dir / "scene_007.mp4").read_bytes() == b"fixture-video"


def test_assembly_preflight_rejects_scene_order_mismatch(tmp_path: Path) -> None:
    clip = tmp_path / "scene_002.mp4"
    audio = tmp_path / "voiceover.wav"
    clip.write_bytes(b"video")
    audio.write_bytes(b"audio")
    rendered = [
        {
            "scene_id": "scene_002",
            "scene_order": 1,
            "status": "rendered",
            "output_path": str(clip),
        }
    ]
    visual_package = {
        "visual_asset_manifest": {
            "visual_scene_plan": {
                "scene_timeline": [{"scene_id": "scene_001", "scene_order": 1}]
            }
        }
    }

    reason = _preflight_failure_reason(rendered, audio, visual_package)

    assert reason == "Rendered scene IDs/order do not match the visual scene plan."
