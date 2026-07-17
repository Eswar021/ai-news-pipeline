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

from src.pipeline.contracts import (
    build_artifact_provenance,
    require_matching_run_id,
    require_parent_fingerprint,
    validate_artifact_provenance,
    visual_plan_artifact_payload,
)

from ..asset_catalog.identity import catalog_identity_payload
from ..common import (
    clean_text,
    counter_dict,
    dedupe,
    iso_now,
    normalize_text_list,
    safe_float,
    short_text,
    slugify,
)
from .config import (
    BROLL_VIDEO_RENDER_KIND,
    MEDIA_RENDER_KINDS,
    NEXT_MODULE,
    PACKAGE_TYPE,
    STORY_TRANSITION_RENDER_KIND,
)
from .clip_selector import select_video_clip_start
from .contract import VisualMediaRequest, VisualMediaResponse
from .llm_client import make_llm
from .prompt_loader import load_system_prompt
from .providers import search_pexels, search_pixabay, search_wikimedia
from .providers.http import download_file
from .ranking import rank_candidates
from .semantic_verifier import verify_ranked_candidates


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
    require_matching_run_id(
        request.run.run_id,
        request.input.visual_scene_planning.data.run_id,
        "visual_scene_planning",
    )
    plan_provenance = _required_plan_provenance(original_plan, request.run.run_id)
    enriched_plan = deepcopy(original_plan)
    scenes = enriched_plan.get("scene_timeline", [])
    media_scenes = [scene for scene in scenes if _scene_uses_catalog_or_external_media(scene)]
    catalog_assets_by_id = _catalog_assets_by_id(enriched_plan)
    external_media_scenes = [
        scene
        for scene in media_scenes
        if not _has_usable_catalog_media(scene, catalog_assets_by_id)
    ]
    candidate_catalog: dict[str, list[dict[str, Any]]] = {}
    selections: list[dict[str, Any]] = []
    provider_errors: list[dict[str, str]] = []
    download_errors: list[dict[str, str]] = []
    fallbacks: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []
    llm_calls: list[dict[str, Any]] = []
    request_outcomes: dict[str, dict[str, Any]] = {}
    request_keys_by_scene: dict[str, str] = {}
    fallback_request_keys: set[str] = set()
    reused_media_scene_count = 0
    fallback_request_budget = request.config.fallback_request_budget
    verification_config = request.config.semantic_verification.model_dump(mode="json")
    verifier_llm = None
    verifier_prompt = ""
    clip_selector_prompt = ""
    if verification_config["enabled"] and external_media_scenes:
        verifier_llm = make_llm(
            model=verification_config["model"],
            temperature=float(verification_config["temperature"]),
        )
        verifier_prompt = load_system_prompt(verification_config["prompt_version"])
        if verification_config["verify_video_clip_frames"]:
            clip_selector_prompt = load_system_prompt(
                verification_config["prompt_version"],
                "video_clip_selector",
            )

    for scene in media_scenes:
        scene_id = clean_text(scene.get("scene_id", "scene_unknown"))
        catalog_selection = _catalog_media_selection(
            scene,
            assets_by_id=catalog_assets_by_id,
            images_dir=images_dir,
            videos_dir=videos_dir,
            request=request,
        )
        if catalog_selection:
            request_key = clean_text(catalog_selection.get("media_request_key")) or (
                f"asset_catalog:{catalog_selection['candidate_id']}"
            )
            request_keys_by_scene[scene_id] = request_key
            cached_outcome = request_outcomes.get(request_key)
            if cached_outcome is not None:
                reused_media_scene_count += 1
                catalog_selection = _selection_for_reused_scene(
                    cached_outcome["selection"],
                    scene,
                    request_key=request_key,
                )
            candidate_catalog[scene_id] = [_catalog_candidate(catalog_selection)]
            selections.append(catalog_selection)
            _attach_selection(scene, catalog_selection)
            request_outcomes.setdefault(
                request_key,
                {
                    "status": "selected",
                    "scene_id": scene_id,
                    "selection": deepcopy(catalog_selection),
                    "candidate_catalog": deepcopy(candidate_catalog[scene_id]),
                },
            )
            continue
        if request.config.trusted_catalog_only:
            request_key = f"trusted_catalog_required:{scene_id}"
            request_keys_by_scene[scene_id] = request_key
            reason = (
                "Scene requested external media without a verified catalog asset_id, "
                "but config.trusted_catalog_only=true. Replan with a source image, "
                "source page, logo, or code-generated explanatory scene."
            )
            candidate_catalog[scene_id] = []
            unresolved.append({"scene_id": scene_id, "reason": reason, "media_request_key": request_key})
            request_outcomes[request_key] = {
                "status": "unresolved",
                "scene_id": scene_id,
                "reason": reason,
                "candidate_catalog": [],
            }
            continue
        _normalize_media_scene_payload(
            scene,
            allow_fallback=request.config.allow_query_fallback,
        )
        request_key = _media_request_key(
            scene,
            reuse_equivalent_images=request.config.reuse_equivalent_image_requests,
        )
        request_keys_by_scene[scene_id] = request_key
        cached_outcome = request_outcomes.get(request_key)
        if cached_outcome is not None:
            reused_media_scene_count += 1
            candidate_catalog[scene_id] = deepcopy(cached_outcome.get("candidate_catalog", []))
            outcome_status = clean_text(cached_outcome.get("status", ""))
            if outcome_status == "selected":
                selection = _selection_for_reused_scene(
                    cached_outcome["selection"],
                    scene,
                    request_key=request_key,
                )
                selections.append(selection)
                _attach_selection(scene, selection)
                continue
            reason = clean_text(cached_outcome.get("reason", ""))
            original_kind = clean_text(scene.get("render_kind", ""))
            if outcome_status == "fallback" and _apply_explicit_fallback(scene, original_kind, reason):
                fallbacks.append(
                    {
                        "scene_id": scene_id,
                        "original_render_kind": original_kind,
                        "reason": reason,
                        "media_request_key": request_key,
                        "reused_from_scene_id": clean_text(cached_outcome.get("scene_id", "")),
                    }
                )
            else:
                unresolved.append(
                    {
                        "scene_id": scene_id,
                        "reason": reason or "Equivalent media request remained unresolved.",
                        "media_request_key": request_key,
                    }
                )
            continue

        candidates, errors = _discover_candidates(scene, request)
        provider_errors.extend(errors)
        ranked = _rank_for_scene(scene, candidates, request)
        if verifier_llm is not None:
            ranked = verify_ranked_candidates(
                scene=scene,
                candidates=ranked,
                config=verification_config,
                llm=verifier_llm,
                system_prompt=verifier_prompt,
                llm_calls=llm_calls,
            )
        scene_catalog = [
            _catalog_candidate(item)
            for item in ranked[: request.config.candidate_catalog_limit_per_scene]
        ]
        candidate_catalog[scene_id] = scene_catalog
        selection, scene_download_errors = _download_best_candidate(
            scene=scene,
            ranked=ranked,
            request=request,
            images_dir=images_dir,
            videos_dir=videos_dir,
            verifier_llm=verifier_llm,
            clip_selector_prompt=clip_selector_prompt,
            llm_calls=llm_calls,
        )
        download_errors.extend(scene_download_errors)
        if selection:
            selection["media_request_key"] = request_key
            selections.append(selection)
            _attach_selection(scene, selection)
            request_outcomes[request_key] = {
                "status": "selected",
                "scene_id": scene_id,
                "selection": deepcopy(selection),
                "candidate_catalog": deepcopy(scene_catalog),
            }
            continue
        reason = _selection_failure_reason(scene, ranked)
        if scene_download_errors:
            reason = f"{reason} First error: {scene_download_errors[0]['error']}"
        if (
            request.config.unresolved_fallback_render_kind
            and len(fallback_request_keys) < fallback_request_budget
        ):
            original_kind = clean_text(scene.get("render_kind", ""))
            if _apply_explicit_fallback(scene, original_kind, reason):
                fallback_request_keys.add(request_key)
                fallbacks.append(
                    {
                        "scene_id": scene_id,
                        "original_render_kind": original_kind,
                        "reason": reason,
                        "media_request_key": request_key,
                    }
                )
                request_outcomes[request_key] = {
                    "status": "fallback",
                    "scene_id": scene_id,
                    "reason": reason,
                    "candidate_catalog": deepcopy(scene_catalog),
                }
            else:
                reason = f"{reason} No narration-derived phrase was available for the configured fallback."
                unresolved.append({"scene_id": scene_id, "reason": reason, "media_request_key": request_key})
                request_outcomes[request_key] = {
                    "status": "unresolved",
                    "scene_id": scene_id,
                    "reason": reason,
                    "candidate_catalog": deepcopy(scene_catalog),
                }
        else:
            if request.config.unresolved_fallback_render_kind:
                reason = (
                    f"{reason} Configured media fallback budget "
                    f"({fallback_request_budget} unique media requests) is exhausted."
                )
            unresolved.append({"scene_id": scene_id, "reason": reason, "media_request_key": request_key})
            request_outcomes[request_key] = {
                "status": "unresolved",
                "scene_id": scene_id,
                "reason": reason,
                "candidate_catalog": deepcopy(scene_catalog),
            }

    enriched_plan["asset_manifest"] = _asset_manifest_for_scenes(scenes)
    enriched_plan["media_discovery"] = {
        "requested_scene_ids": [clean_text(scene.get("scene_id", "")) for scene in media_scenes],
        "request_keys_by_scene": request_keys_by_scene,
        "unique_media_request_count": len(request_outcomes),
        "reused_media_scene_count": reused_media_scene_count,
        "selected_scene_ids": [selection["scene_id"] for selection in selections],
        "fallback_request_count": len(fallback_request_keys),
        "fallback_request_budget": fallback_request_budget,
        "fallbacks": fallbacks,
        "unresolved": unresolved,
        "provider_errors": provider_errors,
        "download_errors": download_errors,
        "semantic_verification": {
            "enabled": verification_config["enabled"],
            "provider": verification_config["provider"],
            "model": verification_config["model"],
            "llm_call_count": len(llm_calls),
        },
    }
    package = {
        "package_type": PACKAGE_TYPE,
        "run_id": request.run.run_id,
        "generated_at": generated_at,
        "output_dir": str(output_dir),
        "original_visual_scene_plan": original_plan,
        "visual_scene_plan": enriched_plan,
        "candidate_catalog": candidate_catalog,
        "request_keys_by_scene": request_keys_by_scene,
        "selections": selections,
        "attribution_manifest": [_attribution_entry(selection) for selection in selections],
        "provider_errors": provider_errors,
        "fallbacks": fallbacks,
        "unresolved": unresolved,
        "llm_calls": llm_calls,
    }
    parents = {
        "visual_plan": plan_provenance["visual_plan_fingerprint"],
        "script": plan_provenance["script_fingerprint"],
    }
    if plan_provenance.get("voiceover_fingerprint"):
        parents["voiceover"] = plan_provenance["voiceover_fingerprint"]
    package["provenance"] = build_artifact_provenance(
        artifact_type="visual_media",
        run_id=request.run.run_id,
        parents=parents,
        script_source=plan_provenance.get("script_source", ""),
        payload=_media_identity_payload(package),
    )
    summary = _build_summary(
        media_scenes=media_scenes,
        selections=selections,
        fallbacks=fallbacks,
        unresolved=unresolved,
        provider_errors=provider_errors,
        download_errors=download_errors,
        candidate_catalog=candidate_catalog,
        llm_calls=llm_calls,
        request_keys_by_scene=request_keys_by_scene,
        unique_media_request_count=len(request_outcomes),
        reused_media_scene_count=reused_media_scene_count,
        fallback_request_count=len(fallback_request_keys),
        fallback_request_budget=fallback_request_budget,
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
        llm_calls=llm_calls,
    )
    result = response.model_dump(mode="json")
    output_dir.mkdir(parents=True, exist_ok=True)
    package_path.write_text(json.dumps(package, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def _catalog_assets_by_id(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    catalog = plan.get("asset_catalog") if isinstance(plan.get("asset_catalog"), dict) else {}
    return {
        clean_text(asset.get("asset_id")): asset
        for asset in catalog.get("assets", [])
        if isinstance(asset, dict) and clean_text(asset.get("asset_id"))
    }


def _has_usable_catalog_media(
    scene: dict[str, Any],
    assets_by_id: dict[str, dict[str, Any]],
) -> bool:
    payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
    asset = assets_by_id.get(clean_text(payload.get("asset_id")))
    if not isinstance(asset, dict):
        return False
    if clean_text(asset.get("status")) != "available":
        return False
    render_kind = clean_text(scene.get("render_kind"))
    if render_kind == STORY_TRANSITION_RENDER_KIND:
        background_type = clean_text(payload.get("background_media_type"))
        expected_types = {
            "image": {"source_image", "official_product_interface", "source_figure"},
            "video": {"source_video", "broll_video"},
        }.get(background_type, set())
        return clean_text(asset.get("asset_type")) in expected_types
    if render_kind == "context_image_scene":
        return clean_text(asset.get("asset_type")) in {
            "source_image",
            "official_product_interface",
            "source_figure",
        }
    return clean_text(asset.get("asset_type")) in {"source_video", "broll_video"}


def _scene_uses_catalog_or_external_media(scene: dict[str, Any]) -> bool:
    render_kind = clean_text(scene.get("render_kind"))
    if render_kind in MEDIA_RENDER_KINDS:
        return True
    if render_kind != STORY_TRANSITION_RENDER_KIND:
        return False
    payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
    return bool(
        clean_text(payload.get("asset_id"))
        and clean_text(payload.get("background_media_type")) in {"image", "video"}
    )


def _catalog_media_selection(
    scene: dict[str, Any],
    *,
    assets_by_id: dict[str, dict[str, Any]],
    images_dir: Path,
    videos_dir: Path | None = None,
    request: VisualMediaRequest | None = None,
) -> dict[str, Any] | None:
    if not _has_usable_catalog_media(scene, assets_by_id):
        return None
    payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
    asset_id = clean_text(payload.get("asset_id"))
    asset = assets_by_id[asset_id]
    source_path = Path(clean_text(asset.get("local_path"))).resolve()
    if not source_path.exists() or not source_path.is_file() or source_path.stat().st_size <= 0:
        raise ValueError(f"Catalog asset {asset_id!r} has no usable local media file")
    suffix = source_path.suffix.lower()
    scene_id = clean_text(scene.get("scene_id", "scene_unknown"))
    render_kind = clean_text(scene.get("render_kind"))
    catalog_asset_type = clean_text(asset.get("asset_type"))
    if catalog_asset_type in {"source_video", "broll_video"}:
        if videos_dir is None or request is None:
            raise ValueError("Catalog video selection requires videos_dir and media-discovery request config")
        if suffix not in {".mp4", ".webm", ".mov", ".m4v"}:
            raise ValueError(f"Catalog asset {asset_id!r} uses unsupported video format {suffix!r}")
        output_path = videos_dir / f"{slugify(scene_id)}_{slugify(asset_id)}.mp4"
        clip_duration = _prepare_catalog_video_clip(
            source_path=source_path,
            output_path=output_path,
            scene=scene,
            request=request,
        )
        media_type = "video"
        content_type = "video/mp4"
        request_key = (
            f"asset_catalog:{asset_id}:"
            f"{round(max(1.0, safe_float(scene.get('duration_seconds'), 6.0)), 2)}"
        )
    else:
        if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            raise ValueError(f"Catalog asset {asset_id!r} uses unsupported image format {suffix!r}")
        output_path = images_dir / f"{slugify(scene_id)}_{slugify(asset_id)}{suffix}"
        if source_path != output_path:
            shutil.copy2(source_path, output_path)
        clip_duration = 0.0
        media_type = "image"
        content_type = _content_type_for_image(output_path)
        request_key = f"asset_catalog:{asset_id}"
    return {
        "candidate_id": asset_id,
        "scene_id": scene_id,
        "render_kind": render_kind,
        "provider": "asset_catalog",
        "media_type": media_type,
        "status": "selected",
        "title": clean_text(asset.get("title")),
        "description": clean_text(asset.get("description")),
        "source_url": clean_text(asset.get("source_url")),
        "download_url": clean_text(asset.get("asset_url")),
        "asset_path": str(output_path),
        "width": asset.get("width"),
        "height": asset.get("height"),
        "downloaded_bytes": output_path.stat().st_size,
        "download_content_type": content_type,
        "clip_start_seconds": 0.0 if media_type == "video" else None,
        "clip_duration_seconds": round(clip_duration, 3) if media_type == "video" else None,
        "media_request_key": request_key,
        "selection_basis": "planner_selected_exact_story_catalog_asset_id",
        "provenance_verification": {
            "status": "trusted_source_asset",
            "passed": True,
            "reason": "The asset was obtained from a selected story source or its owned media.",
        },
        "semantic_verification": {
            "enabled": False,
            "status": "not_independently_reviewed",
            "passed": None,
            "reason": (
                "The visual planner selected this exact story-owned asset for the active beat; "
                "no separate vision suitability review was requested."
            ),
        },
        "narration_suitability": asset.get("narration_suitability")
        or {
            "status": "planner_selected",
            "basis": "exact_asset_id_selected_for_active_script_beat",
            "independent_vision_review": False,
        },
        "review_status": clean_text(asset.get("review_status")),
        "selected_at": iso_now(),
    }


def _prepare_catalog_video_clip(
    *,
    source_path: Path,
    output_path: Path,
    scene: dict[str, Any],
    request: VisualMediaRequest,
) -> float:
    scene_duration = max(1.0, safe_float(scene.get("duration_seconds"), 6.0))
    clip_duration = scene_duration + request.config.video_clip_padding_seconds
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        request.config.ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(source_path),
        "-t",
        f"{clip_duration:.3f}",
        "-vf",
        (
            f"scale={request.config.video_output_width}:-2:"
            "force_original_aspect_ratio=decrease,"
            "crop=trunc(iw/2)*2:trunc(ih/2)*2"
        ),
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
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=request.config.download_timeout_seconds,
    )
    if completed.returncode != 0:
        output_path.unlink(missing_ok=True)
        raise ValueError((completed.stderr or "ffmpeg failed to prepare catalog video")[-1500:])
    if (
        not output_path.exists()
        or output_path.stat().st_size <= 0
        or not _is_valid_video_clip(output_path, request.config.ffprobe_path)
    ):
        output_path.unlink(missing_ok=True)
        raise ValueError("Catalog video could not be prepared as a usable scene clip")
    if output_path.stat().st_size > request.config.max_download_bytes:
        output_path.unlink(missing_ok=True)
        raise ValueError("Prepared catalog video exceeds config.max_download_bytes")
    return clip_duration


def _content_type_for_image(path: Path) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(path.suffix.lower(), "application/octet-stream")


def _required_plan_provenance(plan: dict[str, Any], run_id: str) -> dict[str, Any]:
    provenance = plan.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("visual_scene_plan.provenance is required")
    require_matching_run_id(run_id, provenance.get("run_id"), "visual_scene_plan.provenance")
    validated = validate_artifact_provenance(
        provenance,
        artifact_type="visual_plan",
        run_id=run_id,
        payload=visual_plan_artifact_payload(plan),
        label="visual_scene_plan",
    )
    catalog = plan.get("asset_catalog") if isinstance(plan.get("asset_catalog"), dict) else {}
    if catalog:
        require_matching_run_id(run_id, catalog.get("run_id"), "visual_asset_catalog")
        catalog_provenance = validate_artifact_provenance(
            catalog.get("provenance"),
            artifact_type="visual_asset_catalog",
            run_id=run_id,
            payload=catalog_identity_payload(catalog),
            label="visual_asset_catalog",
        )
        require_parent_fingerprint(
            validated,
            parent_name="asset_catalog",
            expected=catalog_provenance["artifact_fingerprint"],
            label="visual_scene_plan",
        )
    for field in ("visual_plan_fingerprint", "script_fingerprint"):
        if not clean_text(validated.get(field)):
            raise ValueError(f"visual_scene_plan.provenance.{field} is required")
    return validated


def _media_identity_payload(package: dict[str, Any]) -> dict[str, Any]:
    plan = package.get("visual_scene_plan") or {}
    return {
        "selections": package.get("selections", []),
        "fallbacks": package.get("fallbacks", []),
        "unresolved": package.get("unresolved", []),
        "scene_timeline": plan.get("scene_timeline", []),
    }


def _media_request_key(
    scene: dict[str, Any],
    *,
    reuse_equivalent_images: bool,
) -> str:
    scene_id = clean_text(scene.get("scene_id", "scene_unknown"))
    render_kind = clean_text(scene.get("render_kind", ""))
    if not reuse_equivalent_images or render_kind == BROLL_VIDEO_RENDER_KIND:
        return f"scene:{scene_id}"

    payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
    beat_ids = dedupe(
        [
            clean_text(beat.get("beat_id", ""))
            for beat in payload.get("beats", [])
            if isinstance(beat, dict)
        ]
    )
    request_identity = {
        "render_kind": render_kind,
        "story_id": clean_text(scene.get("story_id", "")),
        "script_excerpt": clean_text(scene.get("script_excerpt", "")),
        "visual_intent": clean_text(scene.get("visual_intent", "")),
        "search_queries": normalize_text_list(payload.get("search_queries")),
        "must_show": normalize_text_list(payload.get("must_show")),
        "must_avoid": normalize_text_list(payload.get("must_avoid")),
        "shot_style": clean_text(payload.get("shot_style", "")),
        "beat_ids": beat_ids,
    }
    digest = hashlib.sha256(
        json.dumps(request_identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"{render_kind}:{digest}"


def _discover_candidates(
    scene: dict[str, Any],
    request: VisualMediaRequest,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
    render_kind = clean_text(scene.get("render_kind", ""))
    queries = _queries_for_scene(
        scene,
        allow_fallback=request.config.allow_query_fallback,
    )[: request.config.max_queries_per_scene]
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
    must_show, must_avoid = _media_constraints_for_scene(scene)
    queries = _queries_for_scene(scene, allow_fallback=request.config.allow_query_fallback)
    return rank_candidates(
        candidates,
        query=" ".join(queries),
        visual_intent=clean_text(scene.get("visual_intent", "")),
        must_show=must_show,
        must_avoid=must_avoid,
        scene_duration_seconds=safe_float(scene.get("duration_seconds"), 0.0),
        preferred_aspect_ratio=request.config.preferred_aspect_ratio,
        min_image_width=request.config.min_image_width,
        min_image_height=request.config.min_image_height,
    )


def _queries_for_scene(scene: dict[str, Any], *, allow_fallback: bool) -> list[str]:
    payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
    explicit = normalize_text_list(payload.get("search_queries"))
    must_show, _ = _media_constraints_for_scene(scene)
    requested = dedupe([*must_show, *_beat_media_hints(payload), *explicit])
    fallback = [
        clean_text(scene.get("story_title", "")),
        clean_text(scene.get("visual_intent", "")),
        short_text(clean_text(scene.get("script_excerpt", "")), 120),
    ]
    return dedupe([*requested, *fallback]) if allow_fallback else requested


def _normalize_media_scene_payload(scene: dict[str, Any], *, allow_fallback: bool) -> None:
    payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
    must_show, must_avoid = _media_constraints_for_scene(scene)
    payload["search_queries"] = _queries_for_scene(scene, allow_fallback=allow_fallback)
    payload["must_show"] = must_show
    payload["must_avoid"] = must_avoid
    scene["payload"] = payload


def _media_constraints_for_scene(scene: dict[str, Any]) -> tuple[list[str], list[str]]:
    payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
    must_show = normalize_text_list(payload.get("must_show"))
    must_avoid = normalize_text_list(payload.get("must_avoid"))
    for beat in payload.get("beats", []):
        if not isinstance(beat, dict):
            continue
        brief = beat.get("visual_brief") if isinstance(beat.get("visual_brief"), dict) else {}
        must_show.extend(normalize_text_list(brief.get("must_show")))
        must_avoid.extend(normalize_text_list(brief.get("avoid")))
    return dedupe(must_show), dedupe(must_avoid)


def _beat_media_hints(payload: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    for beat in payload.get("beats", []):
        if not isinstance(beat, dict):
            continue
        brief = beat.get("visual_brief") if isinstance(beat.get("visual_brief"), dict) else {}
        hints.extend(normalize_text_list(brief.get("on_screen_text")))
    return dedupe(hints)


def _selection_failure_reason(
    scene: dict[str, Any],
    ranked: list[dict[str, Any]],
) -> str:
    base = "No usable media candidate could be selected and downloaded."
    for candidate in ranked:
        verification = candidate.get("semantic_verification")
        if not isinstance(verification, dict):
            continue
        reason = clean_text(verification.get("reason", ""))
        if reason:
            title = clean_text(candidate.get("title", "")) or clean_text(candidate.get("candidate_id", ""))
            return f"{base} Best checked candidate {title!r} was rejected: {reason}"
    queries = _queries_for_scene(scene, allow_fallback=False)
    if queries:
        return f"{base} No provider result passed selection for queries: {queries}."
    return f"{base} The scene did not provide a usable concrete search query."


def _download_best_candidate(
    *,
    scene: dict[str, Any],
    ranked: list[dict[str, Any]],
    request: VisualMediaRequest,
    images_dir: Path,
    videos_dir: Path,
    verifier_llm,
    clip_selector_prompt: str,
    llm_calls: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    scene_id = clean_text(scene.get("scene_id", "scene_unknown"))
    render_kind = clean_text(scene.get("render_kind", ""))
    expected_type = "video" if render_kind == BROLL_VIDEO_RENDER_KIND else "image"
    errors: list[dict[str, str]] = []
    for candidate in ranked:
        if candidate.get("media_type") != expected_type:
            continue
        if not _candidate_passes_selection_gate(
            candidate,
        ):
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
                    verifier_llm=verifier_llm,
                    clip_selector_prompt=clip_selector_prompt,
                    llm_calls=llm_calls,
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


def _candidate_passes_selection_gate(
    candidate: dict[str, Any],
) -> bool:
    return bool((candidate.get("semantic_verification") or {}).get("passed"))


def _prepare_video_clip(
    *,
    candidate: dict[str, Any],
    scene: dict[str, Any],
    output_path: Path,
    request: VisualMediaRequest,
    verifier_llm,
    clip_selector_prompt: str,
    llm_calls: list[dict[str, Any]],
) -> tuple[int, str]:
    scene_duration = max(1.0, safe_float(scene.get("duration_seconds"), 6.0))
    clip_duration = scene_duration + request.config.video_clip_padding_seconds
    verification_config = request.config.semantic_verification.model_dump(mode="json")
    clip_selection = {
        "status": "start_at_zero",
        "start_seconds": 0.0,
        "reason": "Semantic video clip selection is disabled.",
    }
    if verification_config["verify_video_clip_frames"] and verifier_llm is not None:
        try:
            clip_selection = select_video_clip_start(
                candidate=candidate,
                scene=scene,
                clip_duration=clip_duration,
                config=verification_config,
                llm=verifier_llm,
                system_prompt=clip_selector_prompt,
                llm_calls=llm_calls,
                ffmpeg_path=request.config.ffmpeg_path,
                timeout_seconds=request.config.download_timeout_seconds,
                user_agent=request.config.user_agent,
                work_dir=output_path.parent,
            )
        except Exception as exc:
            if verification_config["video_clip_failure_policy"] == "reject":
                raise ValueError(f"semantic video clip selection failed: {exc}") from exc
            clip_selection = {
                "status": "start_at_zero_fallback",
                "start_seconds": 0.0,
                "reason": f"Semantic clip selection failed and config permits start-at-zero: {exc}",
            }
    start_seconds = safe_float(clip_selection.get("start_seconds"), 0.0)
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
    candidate["clip_selection"] = clip_selection
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


def _selection_for_reused_scene(
    selection: dict[str, Any],
    scene: dict[str, Any],
    *,
    request_key: str,
) -> dict[str, Any]:
    reused = deepcopy(selection)
    reused["reused_from_scene_id"] = clean_text(selection.get("scene_id", ""))
    reused["scene_id"] = clean_text(scene.get("scene_id", ""))
    reused["render_kind"] = clean_text(scene.get("render_kind", ""))
    reused["media_request_key"] = request_key
    return reused


def _apply_explicit_fallback(scene: dict[str, Any], original_kind: str, reason: str) -> bool:
    original_payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
    headline = clean_text(original_payload.get("overlay_headline", ""))
    phrase = headline or short_text(clean_text(scene.get("script_excerpt", "")), 54)
    if not phrase:
        return False
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
    return True


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
    candidate_catalog: dict[str, list[dict[str, Any]]],
    llm_calls: list[dict[str, Any]],
    request_keys_by_scene: dict[str, str],
    unique_media_request_count: int,
    reused_media_scene_count: int,
    fallback_request_count: int,
    fallback_request_budget: int,
    output_dir: str,
) -> dict[str, Any]:
    failure_reason = "; ".join(f"{item['scene_id']}: {item['reason']}" for item in unresolved[:5])
    unique_catalogs: list[list[dict[str, Any]]] = []
    seen_request_keys: set[str] = set()
    for scene_id, candidates in candidate_catalog.items():
        request_key = request_keys_by_scene.get(scene_id, f"scene:{scene_id}")
        if request_key in seen_request_keys:
            continue
        seen_request_keys.add(request_key)
        unique_catalogs.append(candidates)
    verified = [
        candidate
        for candidates in unique_catalogs
        for candidate in candidates
        if (candidate.get("semantic_verification") or {}).get("status") == "verified"
    ]
    accepted = [
        candidate
        for candidate in verified
        if bool((candidate.get("semantic_verification") or {}).get("passed"))
    ]
    return {
        "requested_media_scene_count": len(media_scenes),
        "unique_media_request_count": unique_media_request_count,
        "reused_media_scene_count": reused_media_scene_count,
        "selected_media_count": len(selections),
        "selected_asset_count": len(
            {clean_text(item.get("asset_path", "")) for item in selections if clean_text(item.get("asset_path", ""))}
        ),
        "selected_image_count": len([item for item in selections if item.get("media_type") == "image"]),
        "selected_video_count": len([item for item in selections if item.get("media_type") == "video"]),
        "fallback_scene_count": len(fallbacks),
        "fallback_request_count": fallback_request_count,
        "fallback_request_budget": fallback_request_budget,
        "unresolved_scene_count": len(unresolved),
        "provider_error_count": len(provider_errors),
        "download_error_count": len(download_errors),
        "semantic_verified_candidate_count": len(verified),
        "semantic_accepted_candidate_count": len(accepted),
        "semantic_rejected_candidate_count": len(verified) - len(accepted),
        "semantic_clip_selection_count": len(
            [
                item
                for item in selections
                if (item.get("clip_selection") or {}).get("status") == "verified"
            ]
        ),
        "catalog_asset_selection_count": len(
            [item for item in selections if clean_text(item.get("provider")) == "asset_catalog"]
        ),
        "llm_call_count": len(llm_calls),
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
