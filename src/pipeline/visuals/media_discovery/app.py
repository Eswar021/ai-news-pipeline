from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any
from urllib.parse import urlparse

from ..common import clean_text, counter_dict, dedupe, iso_now, safe_float, short_text, slugify
from .config import BROLL_VIDEO_RENDER_KIND, MEDIA_RENDER_KINDS, NEXT_MODULE, PACKAGE_TYPE
from .contract import VisualMediaRequest, VisualMediaResponse
from .providers import search_pexels, search_pixabay, search_wikimedia
from .providers.http import download_file
from .ranking import rank_candidates


def run(input_json: dict) -> dict:
    request = VisualMediaRequest.model_validate(input_json)
    generated_at = iso_now()
    output_dir = Path(request.config.output_dir).resolve()
    result_path = output_dir / "visual_media_discovery_result.json"
    package_path = output_dir / "visual_media_package.json"
    summary_path = output_dir / "summary.json"

    if package_path.exists() and not request.config.force:
        raise FileExistsError(f"Visual media output already exists at {package_path}. Set config.force=true to replace it.")
    if request.config.force and output_dir.exists():
        shutil.rmtree(output_dir)

    assets_dir = output_dir / "assets"
    images_dir = assets_dir / "images"
    videos_dir = assets_dir / "videos"
    images_dir.mkdir(parents=True, exist_ok=True)
    videos_dir.mkdir(parents=True, exist_ok=True)

    original_plan = request.input.visual_scene_planning.data.visual_scene_plan
    enriched_plan = deepcopy(original_plan)
    scenes = enriched_plan.get("scene_timeline", [])
    media_scenes = [scene for scene in scenes if clean_text(scene.get("render_kind", "")) in MEDIA_RENDER_KINDS]
    candidate_catalog: dict[str, list[dict[str, Any]]] = {}
    selections: list[dict[str, Any]] = []
    provider_errors: list[dict[str, str]] = []
    download_errors: list[dict[str, str]] = []
    fallbacks: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []

    for scene in media_scenes:
        scene_id = clean_text(scene.get("scene_id", "scene_unknown"))
        candidates, errors = _discover_candidates(scene, request)
        provider_errors.extend(errors)
        ranked = _rank_for_scene(scene, candidates, request)
        candidate_catalog[scene_id] = [_catalog_candidate(item) for item in ranked[: request.config.candidate_catalog_limit_per_scene]]
        selection, scene_download_errors = _download_best_candidate(
            scene=scene,
            ranked=ranked,
            request=request,
            images_dir=images_dir,
            videos_dir=videos_dir,
        )
        download_errors.extend(scene_download_errors)
        if selection:
            selections.append(selection)
            _attach_selection(scene, selection)
            continue
        reason = "No usable media candidate could be selected and downloaded."
        if scene_download_errors:
            reason = f"{reason} First error: {scene_download_errors[0]['error']}"
        if request.config.unresolved_fallback_render_kind:
            original_kind = clean_text(scene.get("render_kind", ""))
            _apply_explicit_fallback(scene, original_kind, reason)
            fallbacks.append({"scene_id": scene_id, "original_render_kind": original_kind, "reason": reason})
        else:
            unresolved.append({"scene_id": scene_id, "reason": reason})

    enriched_plan["asset_manifest"] = _asset_manifest_for_scenes(scenes)
    enriched_plan["media_discovery"] = {
        "requested_scene_ids": [clean_text(scene.get("scene_id", "")) for scene in media_scenes],
        "selected_scene_ids": [selection["scene_id"] for selection in selections],
        "fallbacks": fallbacks,
        "unresolved": unresolved,
        "provider_errors": provider_errors,
        "download_errors": download_errors,
    }
    package = {
        "package_type": PACKAGE_TYPE,
        "run_id": request.run.run_id,
        "generated_at": generated_at,
        "output_dir": str(output_dir),
        "original_visual_scene_plan": original_plan,
        "visual_scene_plan": enriched_plan,
        "candidate_catalog": candidate_catalog,
        "selections": selections,
        "attribution_manifest": [_attribution_entry(selection) for selection in selections],
        "provider_errors": provider_errors,
        "fallbacks": fallbacks,
        "unresolved": unresolved,
    }
    summary = _build_summary(
        media_scenes=media_scenes,
        selections=selections,
        fallbacks=fallbacks,
        unresolved=unresolved,
        provider_errors=provider_errors,
        download_errors=download_errors,
        output_dir=str(output_dir),
    )
    status = _status_from_summary(summary)
    response = VisualMediaResponse(
        status=status,
        data={
            "run_id": request.run.run_id,
            "generated_at": generated_at,
            "visual_media_package": package,
        },
        summary=summary,
        handoff={
            "ready_for_visual_asset_resolution": not unresolved,
            "next_module": NEXT_MODULE,
        },
    )
    result = response.model_dump(mode="json")
    output_dir.mkdir(parents=True, exist_ok=True)
    package_path.write_text(json.dumps(package, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def _discover_candidates(
    scene: dict[str, Any],
    request: VisualMediaRequest,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
    render_kind = clean_text(scene.get("render_kind", ""))
    queries = _queries_for_scene(scene)[: request.config.max_queries_per_scene]
    candidates: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    providers = request.config.providers
    for query in queries:
        if providers.wikimedia.enabled and (
            (render_kind == BROLL_VIDEO_RENDER_KIND and providers.wikimedia.include_videos)
            or (render_kind != BROLL_VIDEO_RENDER_KIND and providers.wikimedia.include_images)
        ):
            _collect_provider(
                candidates,
                errors,
                provider="wikimedia",
                scene_id=clean_text(scene.get("scene_id", "")),
                query=query,
                call=lambda: search_wikimedia(
                    query=query,
                    render_kind=render_kind,
                    endpoint=providers.wikimedia.endpoint,
                    limit=request.config.max_candidates_per_query,
                    timeout_seconds=request.config.request_timeout_seconds,
                    user_agent=request.config.user_agent,
                ),
            )
        if providers.pexels.enabled:
            key = _required_api_key(providers.pexels.api_key_env, "pexels")
            _collect_provider(
                candidates,
                errors,
                provider="pexels",
                scene_id=clean_text(scene.get("scene_id", "")),
                query=query,
                call=lambda: search_pexels(
                    query=query,
                    render_kind=render_kind,
                    api_key=key,
                    photo_endpoint=providers.pexels.photo_endpoint,
                    video_endpoint=providers.pexels.video_endpoint,
                    limit=request.config.max_candidates_per_query,
                    timeout_seconds=request.config.request_timeout_seconds,
                    user_agent=request.config.user_agent,
                ),
            )
        if providers.pixabay.enabled:
            key = _required_api_key(providers.pixabay.api_key_env, "pixabay")
            _collect_provider(
                candidates,
                errors,
                provider="pixabay",
                scene_id=clean_text(scene.get("scene_id", "")),
                query=query,
                call=lambda: search_pixabay(
                    query=query,
                    render_kind=render_kind,
                    api_key=key,
                    photo_endpoint=providers.pixabay.photo_endpoint,
                    video_endpoint=providers.pixabay.video_endpoint,
                    limit=request.config.max_candidates_per_query,
                    timeout_seconds=request.config.request_timeout_seconds,
                    user_agent=request.config.user_agent,
                ),
            )
    del payload
    deduped: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = clean_text(candidate.get("source_url") or candidate.get("download_url") or candidate.get("candidate_id", ""))
        if key and key not in deduped:
            deduped[key] = candidate
    return list(deduped.values()), errors


def _collect_provider(
    candidates: list[dict[str, Any]],
    errors: list[dict[str, str]],
    *,
    provider: str,
    scene_id: str,
    query: str,
    call,
) -> None:
    try:
        found = call()
        for provider_rank, candidate in enumerate(found, start=1):
            candidates.append(
                {
                    **candidate,
                    "matched_query": query,
                    "provider_rank": provider_rank,
                    "retrieved_at": iso_now(),
                }
            )
    except Exception as exc:
        errors.append(
            {
                "scene_id": scene_id,
                "provider": provider,
                "query": query,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )


def _required_api_key(environment_name: str, provider: str) -> str:
    value = clean_text(os.getenv(environment_name, ""))
    if not value:
        raise ValueError(f"{provider} is enabled but environment variable {environment_name} is missing")
    return value


def _rank_for_scene(
    scene: dict[str, Any],
    candidates: list[dict[str, Any]],
    request: VisualMediaRequest,
) -> list[dict[str, Any]]:
    payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
    queries = _queries_for_scene(scene)
    return rank_candidates(
        candidates,
        query=" ".join(queries),
        visual_intent=clean_text(scene.get("visual_intent", "")),
        must_show=[clean_text(value) for value in payload.get("must_show", []) if clean_text(value)],
        must_avoid=[clean_text(value) for value in payload.get("must_avoid", []) if clean_text(value)],
        scene_duration_seconds=safe_float(scene.get("duration_seconds"), 0.0),
        preferred_aspect_ratio=request.config.preferred_aspect_ratio,
        min_image_width=request.config.min_image_width,
        min_image_height=request.config.min_image_height,
    )


def _queries_for_scene(scene: dict[str, Any]) -> list[str]:
    payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
    explicit = [clean_text(value) for value in payload.get("search_queries", []) if clean_text(value)]
    fallback = [
        clean_text(scene.get("story_title", "")),
        clean_text(scene.get("visual_intent", "")),
        short_text(clean_text(scene.get("script_excerpt", "")), 120),
    ]
    return dedupe([*explicit, *fallback])


def _download_best_candidate(
    *,
    scene: dict[str, Any],
    ranked: list[dict[str, Any]],
    request: VisualMediaRequest,
    images_dir: Path,
    videos_dir: Path,
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    scene_id = clean_text(scene.get("scene_id", "scene_unknown"))
    render_kind = clean_text(scene.get("render_kind", ""))
    expected_type = "video" if render_kind == BROLL_VIDEO_RENDER_KIND else "image"
    errors: list[dict[str, str]] = []
    for candidate in ranked:
        if candidate.get("media_type") != expected_type:
            continue
        if safe_float(candidate.get("score"), 0.0) < request.config.minimum_selection_score:
            continue
        suffix = ".mp4" if expected_type == "video" else _file_suffix(candidate)
        folder = videos_dir if expected_type == "video" else images_dir
        filename = f"{slugify(scene_id)}_{slugify(clean_text(candidate.get('provider', 'media')))}_{_short_hash(clean_text(candidate.get('download_url', '')))}{suffix}"
        output_path = folder / filename
        try:
            if expected_type == "video":
                byte_count, content_type = _prepare_video_clip(
                    candidate=candidate,
                    scene=scene,
                    output_path=output_path,
                    request=request,
                )
            else:
                byte_count, content_type = download_file(
                    clean_text(candidate.get("download_url", "")),
                    output_path=output_path,
                    timeout_seconds=request.config.download_timeout_seconds,
                    max_bytes=request.config.max_download_bytes,
                    user_agent=request.config.user_agent,
                )
        except Exception as exc:
            errors.append(
                {
                    "scene_id": scene_id,
                    "candidate_id": clean_text(candidate.get("candidate_id", "")),
                    "provider": clean_text(candidate.get("provider", "")),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        return {
            **_catalog_candidate(candidate),
            "scene_id": scene_id,
            "render_kind": render_kind,
            "status": "selected",
            "asset_path": str(output_path),
            "downloaded_bytes": byte_count,
            "download_content_type": content_type,
            "selected_at": iso_now(),
        }, errors
    return None, errors


def _prepare_video_clip(
    *,
    candidate: dict[str, Any],
    scene: dict[str, Any],
    output_path: Path,
    request: VisualMediaRequest,
) -> tuple[int, str]:
    scene_duration = max(1.0, safe_float(scene.get("duration_seconds"), 6.0))
    clip_duration = scene_duration + request.config.video_clip_padding_seconds
    source_duration = safe_float(candidate.get("duration_seconds"), 0.0)
    max_start = max(0.0, source_duration - clip_duration - 0.25)
    start_seconds = 0.0
    if max_start > 0:
        seed = int(_short_hash(clean_text(scene.get("scene_id", ""))), 16)
        start_seconds = min(max_start, 5.0 + (seed % 2000) / 100.0)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        request.config.ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{start_seconds:.3f}",
        "-user_agent",
        request.config.user_agent,
        "-i",
        clean_text(candidate.get("download_url", "")),
        "-t",
        f"{clip_duration:.3f}",
        "-vf",
        f"scale={request.config.video_output_width}:-2:force_original_aspect_ratio=decrease,crop=trunc(iw/2)*2:trunc(ih/2)*2",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=request.config.download_timeout_seconds,
        )
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise ValueError("ffmpeg did not produce a usable video clip")
    if not _is_valid_video_clip(output_path, request.config.ffprobe_path):
        output_path.unlink(missing_ok=True)
        raise ValueError("ffmpeg produced a video container without a usable video stream")
    if output_path.stat().st_size > request.config.max_download_bytes:
        output_path.unlink(missing_ok=True)
        raise ValueError("prepared video clip exceeds config.max_download_bytes")
    candidate["clip_start_seconds"] = round(start_seconds, 3)
    candidate["clip_duration_seconds"] = round(clip_duration, 3)
    return output_path.stat().st_size, "video/mp4"


def _is_valid_video_clip(path: Path, ffprobe_path: str) -> bool:
    try:
        probe = subprocess.run(
            [
                ffprobe_path,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,duration",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        data = json.loads(probe.stdout or "{}")
    except Exception:
        return False
    streams = data.get("streams") if isinstance(data, dict) else []
    if not streams or not isinstance(streams[0], dict):
        return False
    stream = streams[0]
    return safe_float(stream.get("width"), 0.0) > 0 and safe_float(stream.get("height"), 0.0) > 0 and safe_float(stream.get("duration"), 0.0) > 0


def _catalog_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in candidate.items() if key != "download_url"} | {
        "download_url": clean_text(candidate.get("download_url", "")),
    }


def _attach_selection(scene: dict[str, Any], selection: dict[str, Any]) -> None:
    payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
    payload["media_selection_id"] = selection.get("candidate_id", "")
    payload["selected_media_type"] = selection.get("media_type", "")
    payload["selected_media_provider"] = selection.get("provider", "")
    scene["payload"] = payload


def _apply_explicit_fallback(scene: dict[str, Any], original_kind: str, reason: str) -> None:
    original_payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
    headline = clean_text(original_payload.get("overlay_headline", ""))
    phrase = headline or short_text(clean_text(scene.get("script_excerpt", "")), 54) or "Next signal"
    beats = original_payload.get("beats") if isinstance(original_payload.get("beats"), list) else []
    scene["render_kind"] = "kinetic_type_scene"
    scene["visual_intent"] = "Explicit media-discovery fallback: emphasize the narration phrase when no usable remote media is available."
    scene["payload"] = {
        "phrases": [phrase],
        "emphasis_words": [word for word in phrase.split() if len(word) > 4][:4],
        "animation_style": "highlight_sweep",
        "background_motif": "newsroom_grid",
        "beats": beats,
        "media_fallback": {
            "original_render_kind": original_kind,
            "reason": reason,
        },
    }


def _asset_manifest_for_scenes(scenes: list[dict[str, Any]]) -> dict[str, Any]:
    requests: list[dict[str, Any]] = []
    for scene in scenes:
        kind = clean_text(scene.get("render_kind", ""))
        if kind in {"source_article_scene", "quote_or_claim_highlight_scene"}:
            asset_type = "source_screenshot"
        elif kind == "logo_reveal_scene":
            asset_type = "logo_asset"
        elif kind == "context_image_scene":
            asset_type = "context_image"
        elif kind == "broll_video_scene":
            asset_type = "broll_video"
        else:
            asset_type = "none"
        requests.append(
            {
                "asset_request_id": f"asset_{int(scene.get('scene_order', len(requests) + 1)):03d}",
                "scene_id": clean_text(scene.get("scene_id", "")),
                "render_kind": kind,
                "asset_type": asset_type,
                "required": asset_type != "none",
                "payload": scene.get("payload", {}),
            }
        )
    return {
        "asset_request_count": len(requests),
        "asset_type_counts": counter_dict([request["asset_type"] for request in requests]),
        "requests": requests,
    }


def _attribution_entry(selection: dict[str, Any]) -> dict[str, Any]:
    return {
        "scene_id": selection.get("scene_id", ""),
        "candidate_id": selection.get("candidate_id", ""),
        "provider": selection.get("provider", ""),
        "creator": selection.get("creator", ""),
        "attribution": selection.get("attribution", ""),
        "license": selection.get("license", ""),
        "license_url": selection.get("license_url", ""),
        "source_url": selection.get("source_url", ""),
        "asset_path": selection.get("asset_path", ""),
    }


def _build_summary(
    *,
    media_scenes: list[dict[str, Any]],
    selections: list[dict[str, Any]],
    fallbacks: list[dict[str, str]],
    unresolved: list[dict[str, str]],
    provider_errors: list[dict[str, str]],
    download_errors: list[dict[str, str]],
    output_dir: str,
) -> dict[str, Any]:
    failure_reason = "; ".join(f"{item['scene_id']}: {item['reason']}" for item in unresolved[:5])
    return {
        "requested_media_scene_count": len(media_scenes),
        "selected_media_count": len(selections),
        "selected_image_count": len([item for item in selections if item.get("media_type") == "image"]),
        "selected_video_count": len([item for item in selections if item.get("media_type") == "video"]),
        "fallback_scene_count": len(fallbacks),
        "unresolved_scene_count": len(unresolved),
        "provider_error_count": len(provider_errors),
        "download_error_count": len(download_errors),
        "provider_counts": counter_dict([clean_text(item.get("provider", "")) for item in selections]),
        "output_dir": output_dir,
        "failure_reason": failure_reason,
    }


def _status_from_summary(summary: dict[str, Any]) -> str:
    if summary["unresolved_scene_count"]:
        return "failed"
    if summary["fallback_scene_count"] or summary["provider_error_count"] or summary["download_error_count"]:
        return "partial"
    return "ok"


def _file_suffix(candidate: dict[str, Any]) -> str:
    mime = clean_text(candidate.get("mime_type", "")).lower()
    mime_suffix = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/ogg": ".ogv",
    }.get(mime)
    if mime_suffix:
        return mime_suffix
    suffix = Path(urlparse(clean_text(candidate.get("download_url", ""))).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".webm", ".ogv"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".mp4" if candidate.get("media_type") == "video" else ".jpg"


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
