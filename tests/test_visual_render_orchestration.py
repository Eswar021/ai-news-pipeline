from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from src.pipeline.visuals.render import app as render_app
from src.pipeline.visuals.render.contract import VisualRenderConfig, VisualRenderRequest
from src.pipeline.visuals.assembly import app as assembly_app
from src.pipeline.visuals.assembly.app import _ffmpeg_command, _preflight_failure_reason
from src.pipeline.visuals.assembly.contract import VideoAssemblyConfig


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


def test_render_config_selects_hyperframes_explicitly() -> None:
    config = VisualRenderConfig(
        output_dir="render",
        backend="hyperframes",
        hyperframes_quality="high",
    )

    assert config.backend == "hyperframes"
    assert config.hyperframes_quality == "high"


def test_hyperframes_project_copies_media_and_embeds_scene_spec(tmp_path: Path) -> None:
    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    (engine_dir / "node_modules").mkdir()
    (engine_dir / "hyperframes.json").write_text("{}", encoding="utf-8")
    (engine_dir / "index.template.html").write_text(
        "__WIDTH__ __HEIGHT__ __FPS__ __DURATION__ "
        '<script type="application/json">__SCENE_SPEC_JSON__</script>',
        encoding="utf-8",
    )
    image = tmp_path / "source image.jpg"
    image.write_bytes(b"fixture-image")
    spec = {
        "width": 1280,
        "height": 720,
        "fps": 30,
        "duration_seconds": 6.25,
        "scene": {
            "scene_id": "scene/001",
            "render_kind": "context_image_scene",
            "payload": {},
            "resolved_asset": {"asset_path": str(image)},
        },
    }

    project_dir = tmp_path / "project"
    render_app._write_hyperframes_project(
        project_dir=project_dir,
        engine_dir=engine_dir,
        spec=spec,
    )

    html = (project_dir / "index.html").read_text(encoding="utf-8")
    assert "1280 720 30 6.25" in html
    assert '"asset_render_url":"assets/scene_001.jpg"' in html
    assert (project_dir / "assets" / "scene_001.jpg").read_bytes() == b"fixture-image"


def test_hyperframes_rejects_unsupported_scene_before_render(tmp_path: Path) -> None:
    request = _request(tmp_path, backend="hyperframes")
    specs_dir = tmp_path / "specs"
    scenes_dir = tmp_path / "scenes"
    specs_dir.mkdir()
    scenes_dir.mkdir()

    result = render_app._render_scenes_hyperframes(
        render_scenes=[
            {
                "scene_id": "scene_legacy",
                "scene_order": 1,
                "render_kind": "trend_line_scene",
                "duration_seconds": 5,
                "payload": {"headline": "Legacy specialist visual"},
            }
        ],
        engine_dir=tmp_path / "missing-engine",
        specs_dir=specs_dir,
        scenes_dir=scenes_dir,
        request=request,
        render_settings={"width": 1280, "height": 720, "fps": 30},
        duration_cap=14,
    )

    assert result[0]["status"] == "failed"
    assert "does not support render_kind" in result[0]["error"]


def test_hyperframes_avoids_nested_worker_multiplication(tmp_path: Path) -> None:
    parallel_request = _request(
        tmp_path,
        backend="hyperframes",
        worker_count=4,
        frame_concurrency=3,
    )
    focused_request = _request(
        tmp_path,
        backend="hyperframes",
        worker_count=1,
        frame_concurrency=3,
    )

    assert render_app._hyperframes_frame_workers(parallel_request) == 1
    assert render_app._hyperframes_frame_workers(focused_request) == 3


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


def test_persistent_scene_cache_skips_unchanged_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(
        tmp_path,
        cache_dir=str(tmp_path / "cache"),
        reuse_cached_scenes=True,
        batch_renderer_enabled=False,
    )
    scene = {
        "scene_id": "scene_001",
        "scene_order": 1,
        "render_kind": "kinetic_type_scene",
        "duration_seconds": 5,
        "payload": {"phrases": ["Cache this scene"]},
    }
    render_calls = 0

    monkeypatch.setattr(
        render_app,
        "_scene_render_spec",
        lambda scene, request, settings: {"duration_seconds": 5, "scene": scene},
    )
    monkeypatch.setattr(render_app, "_prepare_shared_runtime_asset", lambda *args: None)
    monkeypatch.setattr(render_app, "_engine_fingerprint", lambda path: "engine-v1")
    monkeypatch.setattr(render_app, "_build_shared_bundle", lambda **kwargs: ("", None))
    monkeypatch.setattr(
        render_app,
        "_is_valid_rendered_video",
        lambda path: path.exists() and path.stat().st_size > 0,
    )

    def fake_render(**kwargs: object) -> dict[int, dict]:
        nonlocal render_calls
        render_calls += 1
        job = kwargs["jobs"][0]  # type: ignore[index]
        job["output_path"].write_bytes(b"rendered scene")
        return {
            job["index"]: render_app._rendered_scene(
                job["scene"],
                job["spec_path"],
                job["output_path"],
                job["spec"],
            )
        }

    monkeypatch.setattr(render_app, "_render_prepared_jobs", fake_render)
    settings = {"width": 1280, "height": 720, "fps": 30}
    for path in (
        tmp_path / "first" / "specs",
        tmp_path / "first" / "scenes",
        tmp_path / "second" / "specs",
        tmp_path / "second" / "scenes",
    ):
        path.mkdir(parents=True)
    first = render_app._render_scenes(
        render_scenes=[scene],
        engine_dir=tmp_path,
        specs_dir=tmp_path / "first" / "specs",
        scenes_dir=tmp_path / "first" / "scenes",
        request=request,
        render_settings=settings,
        duration_cap=14,
    )
    second = render_app._render_scenes(
        render_scenes=[scene],
        engine_dir=tmp_path,
        specs_dir=tmp_path / "second" / "specs",
        scenes_dir=tmp_path / "second" / "scenes",
        request=request,
        render_settings=settings,
        duration_cap=14,
    )

    assert render_calls == 1
    assert first[0]["cache_status"] == "stored"
    assert second[0]["cache_status"] == "hit"
    assert Path(second[0]["output_path"]).read_bytes() == b"rendered scene"


def test_assembly_strips_legacy_scene_audio_without_reencoding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "scene_001.mp4"
    source.write_bytes(b"legacy scene with silent audio")
    commands: list[list[str]] = []

    def fake_stream_types(_ffprobe_path: str, path: Path) -> set[str]:
        return {"video", "audio"} if path == source else {"video"}

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        Path(command[-1]).write_bytes(b"video only")
        return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(assembly_app, "_probe_stream_types", fake_stream_types)
    monkeypatch.setattr(assembly_app.subprocess, "run", fake_run)

    prepared, normalized_count = assembly_app._prepare_video_only_scenes(
        [{"scene_id": "scene_001", "output_path": str(source)}],
        output_dir=tmp_path / "assembly",
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
    )

    assert normalized_count == 1
    assert prepared[0]["output_path"] != str(source)
    assert Path(prepared[0]["output_path"]).read_bytes() == b"video only"
    assert "-c:v" in commands[0]
    assert "copy" in commands[0]
    assert "-an" in commands[0]


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


def test_assembly_defaults_to_boundary_safe_video_encoding(tmp_path: Path) -> None:
    request = SimpleNamespace(
        config=VideoAssemblyConfig(output_dir=str(tmp_path / "assembly"))
    )

    command = _ffmpeg_command(
        request,
        tmp_path / "scenes.txt",
        tmp_path / "voiceover.wav",
        tmp_path / "final.mp4",
        reencode=False,
    )

    codec_index = command.index("-c:v")
    assert command[codec_index + 1] == "libx264"
    assert command[command.index("-preset") + 1] == "medium"
    assert command[command.index("-crf") + 1] == "18"
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"


def test_assembly_stream_copy_requires_explicit_boundary_normalization_opt_out(
    tmp_path: Path,
) -> None:
    request = SimpleNamespace(
        config=VideoAssemblyConfig(
            output_dir=str(tmp_path / "assembly"),
            video_codec="copy",
            normalize_scene_boundaries=False,
        )
    )

    command = _ffmpeg_command(
        request,
        tmp_path / "scenes.txt",
        tmp_path / "voiceover.wav",
        tmp_path / "final.mp4",
        reencode=False,
    )

    codec_index = command.index("-c:v")
    assert command[codec_index + 1] == "copy"
    assert "-preset" not in command
