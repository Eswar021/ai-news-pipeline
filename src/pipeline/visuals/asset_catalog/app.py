from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
import io
import json
import math
from pathlib import Path
import shutil
import subprocess
from typing import Any
from urllib.parse import urljoin, urlparse

from PIL import Image, ImageDraw, ImageOps
import requests

from src.pipeline.contracts import (
    artifact_fingerprint,
    build_artifact_provenance,
    file_sha256,
    require_matching_run_id,
    validate_script_provenance,
)

from ..common import clean_text, counter_dict, dedupe, first_url, iso_now, screenshot_target_candidates, slugify
from ..generators.logo_reveal.resolver import simple_icon_export_for
from .config import CATALOG_VERSION, NEXT_MODULE, PACKAGE_TYPE
from .contract import AssetCatalogRequest, AssetCatalogResponse
from .identity import catalog_identity_payload


def _optional_int(value: Any) -> int | None:
    try:
        parsed = int(str(value or "").strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _largest_srcset_url(srcset: str) -> str:
    candidates: list[tuple[float, str]] = []
    for item in clean_text(srcset).split(","):
        parts = item.strip().split()
        if not parts:
            continue
        weight = 1.0
        if len(parts) > 1:
            descriptor = parts[-1].lower()
            try:
                if descriptor.endswith("w"):
                    weight = float(descriptor[:-1])
                elif descriptor.endswith("x"):
                    weight = float(descriptor[:-1]) * 1000
            except ValueError:
                weight = 1.0
        candidates.append((weight, parts[0]))
    return max(candidates, default=(0.0, ""), key=lambda item: item[0])[1]


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.metadata: dict[str, str] = {}
        self.image_candidates: list[dict[str, Any]] = []
        self.video_candidates: list[dict[str, Any]] = []
        self.linked_video_candidates: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {clean_text(key).lower(): clean_text(value) for key, value in attrs}
        if tag.lower() == "meta":
            name = clean_text(values.get("property") or values.get("name")).lower()
            content = clean_text(values.get("content"))
            if name and content and name not in self.metadata:
                self.metadata[name] = content
        elif tag.lower() == "link":
            rel = clean_text(values.get("rel")).lower()
            href = clean_text(values.get("href"))
            if rel == "image_src" and href:
                self.metadata.setdefault("image_src", href)
        elif tag.lower() == "img":
            src = clean_text(
                values.get("src")
                or values.get("data-src")
                or values.get("data-lazy-src")
                or values.get("data-original")
            )
            srcset = clean_text(values.get("srcset") or values.get("data-srcset"))
            src = _largest_srcset_url(srcset) or src
            if src:
                self.image_candidates.append(
                    {
                        "url": src,
                        "alt": clean_text(values.get("alt")),
                        "title": clean_text(values.get("title")),
                        "declared_width": _optional_int(values.get("width")),
                        "declared_height": _optional_int(values.get("height")),
                        "image_role": "article_image",
                    }
                )
        elif tag.lower() == "video":
            poster = clean_text(values.get("poster"))
            if poster:
                self.image_candidates.append(
                    {
                        "url": poster,
                        "alt": "",
                        "title": "",
                        "declared_width": _optional_int(values.get("width")),
                        "declared_height": _optional_int(values.get("height")),
                        "image_role": "video_poster",
                    }
                )
            src = clean_text(values.get("src"))
            if src:
                self.video_candidates.append(
                    {
                        "url": src,
                        "mime_type": clean_text(values.get("type")),
                        "video_role": "embedded_video",
                    }
                )
        elif tag.lower() == "source":
            src = clean_text(values.get("src"))
            mime_type = clean_text(values.get("type")).lower()
            suffix = Path(urlparse(src).path).suffix.lower()
            if src and (mime_type.startswith("video/") or suffix in {".mp4", ".webm", ".mov", ".m4v"}):
                self.video_candidates.append(
                    {
                        "url": src,
                        "mime_type": mime_type,
                        "video_role": "embedded_video_source",
                    }
                )
        elif tag.lower() in {"a", "iframe"}:
            candidate_url = clean_text(
                values.get("href") if tag.lower() == "a" else values.get("src")
            )
            provider = _source_video_provider(candidate_url)
            if provider:
                self.linked_video_candidates.append(
                    {
                        "url": candidate_url,
                        "provider": provider,
                        "video_role": (
                            "source_page_video_link"
                            if tag.lower() == "a"
                            else "source_page_video_embed"
                        ),
                    }
                )


def run(input_json: dict) -> dict:
    request = AssetCatalogRequest.model_validate(input_json)
    generated_at = iso_now()
    run_id = request.run.run_id
    output_dir = Path(request.config.output_dir).resolve()

    require_matching_run_id(run_id, request.input.script_generation.data.run_id, "script_generation")
    require_matching_run_id(run_id, request.input.video_packaging.data.run_id, "video_packaging")
    script_package = request.input.script_generation.data.script_package
    script_provenance = validate_script_provenance(
        script_package,
        run_id=run_id,
        upstream_run_id=request.input.script_generation.data.run_id,
    )

    if request.config.force and output_dir.exists():
        shutil.rmtree(output_dir)
    source_images_dir = output_dir / "source_images"
    source_videos_dir = output_dir / "source_videos"
    source_images_dir.mkdir(parents=True, exist_ok=True)
    source_videos_dir.mkdir(parents=True, exist_ok=True)

    stories = _selected_stories(request.input.video_packaging.data.video_packet)
    sections_by_story = _sections_by_story(script_package)
    script_hints_by_story = _script_hints_by_story(script_package)
    truth_targets_by_record = _truth_targets_by_record(script_package)
    briefs_by_story = {
        story_id: _asset_briefs_for_story(
            story_id=story_id,
            section=sections_by_story.get(story_id, {}),
            script_hint=script_hints_by_story.get(story_id, {}),
        )
        for story_id in [clean_text(story.get("story_id")) for story in stories]
        if story_id
    }

    assets: list[dict[str, Any]] = []
    warnings: list[str] = []
    records_to_fetch: list[tuple[str, dict[str, Any]]] = []
    for story in stories:
        story_id = clean_text(story.get("story_id"))
        records = [record for record in story.get("records", []) if isinstance(record, dict)]
        for record in records:
            record_key = clean_text(record.get("record_key"))
            url = first_url(record)
            if request.config.collect_source_pages and record_key and url:
                assets.append(
                    _source_page_asset(
                        story_id,
                        record,
                        beat_targets=truth_targets_by_record.get(record_key, []),
                    )
                )
            if (
                (request.config.collect_source_images or request.config.collect_source_videos)
                and record_key
                and url
                and request.config.page_metadata.enabled
            ):
                records_to_fetch.append((story_id, record))
        if request.config.collect_resolvable_logos:
            assets.extend(
                _logo_assets_for_story(
                    story,
                    script_hints_by_story.get(story_id, {}),
                    asset_briefs=briefs_by_story.get(story_id, []),
                    local_logo_dir=Path(request.config.local_logo_dir).resolve()
                    if clean_text(request.config.local_logo_dir)
                    else None,
                )
            )

    page_results = _collect_source_media(
        records_to_fetch,
        image_output_dir=source_images_dir,
        video_output_dir=source_videos_dir,
        config={
            **request.config.page_metadata.model_dump(mode="json"),
            "collect_source_images": request.config.collect_source_images,
            "collect_source_videos": request.config.collect_source_videos,
            "source_linked_video": request.config.source_linked_video.model_dump(mode="json"),
        },
    )
    source_candidate_telemetry: list[dict[str, Any]] = []
    for result in page_results:
        if result.get("asset"):
            assets.append(result["asset"])
        assets.extend(asset for asset in result.get("assets", []) if isinstance(asset, dict))
        if result.get("warning"):
            warnings.append(clean_text(result["warning"]))
        warnings.extend(clean_text(item) for item in result.get("warnings", []) if clean_text(item))
        if isinstance(result.get("candidate_telemetry"), dict):
            source_candidate_telemetry.append(result["candidate_telemetry"])

    candidate_filtering = _aggregate_candidate_telemetry(source_candidate_telemetry)
    candidate_summary = {
        key: value
        for key, value in candidate_filtering.items()
        if key != "source_record_candidate_telemetry"
    }

    assets, duplicate_filtering = _dedupe_assets(
        assets,
        near_duplicate_hash_distance=request.config.page_metadata.near_duplicate_hash_distance,
    )
    assets_by_story: dict[str, list[dict[str, Any]]] = {}
    for asset in assets:
        assets_by_story.setdefault(clean_text(asset.get("story_id")), []).append(asset)

    story_catalogs: list[dict[str, Any]] = []
    missing_anchor_story_ids: list[str] = []
    unresolved_request_count = 0
    for story in stories:
        story_id = clean_text(story.get("story_id"))
        story_assets = assets_by_story.get(story_id, [])
        briefs = briefs_by_story.get(story_id, [])
        resolved_briefs = [_bind_brief_to_assets(brief, story_assets) for brief in briefs]
        unresolved_request_count += len(
            [brief for brief in resolved_briefs if brief.get("resolution_status") == "unresolved"]
        )
        if not any(asset.get("status") == "available" for asset in story_assets):
            missing_anchor_story_ids.append(story_id)
        story_catalogs.append(
            {
                "story_id": story_id,
                "story_title": clean_text(story.get("story_title")),
                "story_identity": story.get("story_identity", {}),
                "asset_briefs": resolved_briefs,
                "assets": story_assets,
                "available_asset_ids": [
                    asset["asset_id"] for asset in story_assets if asset.get("status") == "available"
                ],
            }
        )

    contact_sheet_path = _build_contact_sheet(
        [
            asset
            for asset in assets
            if clean_text(asset.get("local_path"))
            and clean_text(asset.get("asset_type")) in {"source_image", "logo"}
        ],
        output_dir / "catalog_contact_sheet.jpg",
        request.config.contact_sheet.model_dump(mode="json"),
    )
    catalog = {
        "package_type": PACKAGE_TYPE,
        "catalog_version": CATALOG_VERSION,
        "run_id": run_id,
        "generated_at": generated_at,
        "research_mode": request.config.research_mode,
        "story_catalogs": story_catalogs,
        "assets": assets,
        "contact_sheet_path": str(contact_sheet_path) if contact_sheet_path else "",
        "review_policy": {
            "trusted_source_assets_are_usable": True,
            "provenance_trust_does_not_imply_narration_suitability": True,
            "external_media_requires_manual_or_configured_semantic_review": True,
            "unresolved_requests_are_not_silently_substituted": True,
        },
        "structural_filtering": {
            "image_minimum_short_edge": request.config.page_metadata.min_image_short_edge,
            "image_minimum_pixel_area": request.config.page_metadata.min_image_pixel_area,
            "image_aspect_ratio_range": [
                request.config.page_metadata.min_image_aspect_ratio,
                request.config.page_metadata.max_image_aspect_ratio,
            ],
            "near_duplicate_hash_distance": (
                request.config.page_metadata.near_duplicate_hash_distance
            ),
            "source_candidate_policy": {
                "ordering": "declared_source_hero_then_document_order",
                "semantic_reranking_applied": False,
                "resource_limits_are_reported": True,
            },
            **candidate_filtering,
            **duplicate_filtering,
        },
        "warnings": dedupe(warnings),
    }
    catalog["provenance"] = build_artifact_provenance(
        artifact_type="visual_asset_catalog",
        run_id=run_id,
        parents={"script": script_provenance["script_fingerprint"]},
        script_source=script_provenance.get("script_source", ""),
        payload=catalog_identity_payload(catalog),
    )

    status = "ok"
    failure_reason = ""
    if request.config.require_real_anchor_per_story and missing_anchor_story_ids:
        status = "failed"
        failure_reason = f"Stories are missing a trusted visual anchor: {missing_anchor_story_ids}"
    summary = {
        "story_count": len(stories),
        "asset_brief_count": sum(len(item["asset_briefs"]) for item in story_catalogs),
        "asset_count": len(assets),
        "asset_type_counts": counter_dict([clean_text(asset.get("asset_type")) for asset in assets]),
        "source_page_count": len([asset for asset in assets if asset.get("asset_type") == "source_page"]),
        "source_image_count": len([asset for asset in assets if asset.get("asset_type") == "source_image"]),
        "source_video_count": len([asset for asset in assets if asset.get("asset_type") == "source_video"]),
        "logo_count": len([asset for asset in assets if asset.get("asset_type") == "logo"]),
        "unresolved_request_count": unresolved_request_count,
        "warning_count": len(catalog["warnings"]),
        "duplicate_asset_id_count": duplicate_filtering["duplicate_asset_id_count"],
        "exact_duplicate_image_count": duplicate_filtering["exact_duplicate_image_count"],
        "near_duplicate_image_count": duplicate_filtering["near_duplicate_image_count"],
        **candidate_summary,
        "missing_anchor_story_ids": missing_anchor_story_ids,
        "contact_sheet_path": catalog["contact_sheet_path"],
        "failure_reason": failure_reason,
    }
    response = AssetCatalogResponse(
        status=status,
        data={
            "run_id": run_id,
            "generated_at": generated_at,
            "visual_asset_catalog": catalog,
        },
        summary=summary,
        handoff={
            "ready_for_visual_planning": status == "ok",
            "requires_manual_external_media_review": unresolved_request_count > 0,
            "next_module": NEXT_MODULE,
        },
    )
    return response.model_dump(mode="json")


def _selected_stories(video_packet: dict[str, Any]) -> list[dict[str, Any]]:
    stories = video_packet.get("stories") or video_packet.get("selected_stories")
    if not isinstance(stories, list) or not stories:
        raise ValueError("video_packaging.data.video_packet.stories must be a non-empty list")
    return [story for story in stories if isinstance(story, dict)]


def _sections_by_story(script_package: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sections = script_package.get("sections")
    if not isinstance(sections, list):
        raise ValueError("script_package.sections must be a list")
    return {
        clean_text(section.get("story_id")): section
        for section in sections
        if isinstance(section, dict)
        and clean_text(section.get("section_type")) == "story"
        and clean_text(section.get("story_id"))
    }


def _script_hints_by_story(script_package: dict[str, Any]) -> dict[str, dict[str, Any]]:
    hints = script_package.get("story_asset_hints")
    if not isinstance(hints, list):
        return {}
    return {
        clean_text(item.get("story_id")): item
        for item in hints
        if isinstance(item, dict) and clean_text(item.get("story_id"))
    }


def _truth_targets_by_record(script_package: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    truth_items: dict[str, dict[str, Any]] = {}
    for index in script_package.get("story_truth_indexes", []):
        if not isinstance(index, dict):
            continue
        story_id = clean_text(index.get("story_id"))
        for item in index.get("items", []):
            if not isinstance(item, dict):
                continue
            truth_id = clean_text(item.get("truth_id"))
            if truth_id:
                truth_items[truth_id] = {**item, "story_id": story_id}

    targets: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str, str]] = set()
    for section in script_package.get("sections", []):
        if not isinstance(section, dict) or clean_text(section.get("section_type")) != "story":
            continue
        story_id = clean_text(section.get("story_id"))
        for beat in section.get("beats", []):
            if not isinstance(beat, dict):
                continue
            beat_id = clean_text(beat.get("beat_id"))
            for truth_id in beat.get("support_truth_ids", []):
                item = truth_items.get(clean_text(truth_id), {})
                record_key = clean_text(item.get("record_key"))
                source_text = clean_text(item.get("source_text"))
                if (
                    not record_key
                    or not source_text
                    or clean_text(item.get("story_id")) != story_id
                ):
                    continue
                signature = (record_key, beat_id, source_text.casefold())
                if signature in seen:
                    continue
                seen.add(signature)
                targets.setdefault(record_key, []).append(
                    {
                        "beat_id": beat_id,
                        "truth_id": clean_text(item.get("truth_id")),
                        "source_text": source_text,
                        "source_field": clean_text(item.get("source_field")),
                        "source_order": int(item.get("source_order", 0) or 0),
                    }
                )
    return targets


def _asset_briefs_for_story(
    *,
    story_id: str,
    section: dict[str, Any],
    script_hint: dict[str, Any],
) -> list[dict[str, Any]]:
    briefs: list[dict[str, Any]] = []
    beats = section.get("beats") if isinstance(section.get("beats"), list) else []
    for beat in beats:
        if not isinstance(beat, dict):
            continue
        visual = beat.get("visual_brief") if isinstance(beat.get("visual_brief"), dict) else {}
        beat_id = clean_text(beat.get("beat_id"))
        preferred = _normalized_asset_types(visual.get("preferred_asset_types"))
        must_show = _text_list(visual.get("must_show"))
        must_avoid = _text_list(visual.get("avoid"))
        source_keys = _text_list(beat.get("source_record_keys"))
        purpose = clean_text(visual.get("purpose") or beat.get("visual_goal"))
        subject = must_show[0] if must_show else clean_text(visual.get("on_screen_text") or purpose)
        if not preferred:
            preferred = ["source_page"] if source_keys else ["code_graphic"]
        brief_seed = {
            "story_id": story_id,
            "beat_id": beat_id,
            "asset_types": preferred,
            "subject": subject,
            "source_record_keys": source_keys,
        }
        briefs.append(
            {
                "asset_request_id": _stable_id("request", brief_seed),
                "story_id": story_id,
                "beat_ids": [beat_id] if beat_id else [],
                "visual_goal": clean_text(beat.get("visual_goal") or visual.get("visual_intent")),
                "purpose": purpose,
                "subject": subject,
                "requested_asset_types": preferred,
                "must_show": must_show,
                "must_avoid": must_avoid,
                "preferred_record_keys": source_keys,
                "search_queries": dedupe([subject, clean_text(visual.get("on_screen_text"))]),
                "brief_source": "canonical_script_visual_brief",
            }
        )

    if not briefs:
        source_pages = script_hint.get("source_pages") if isinstance(script_hint.get("source_pages"), list) else []
        for source in source_pages:
            if not isinstance(source, dict):
                continue
            record_key = clean_text(source.get("record_key"))
            subject = clean_text(source.get("title"))
            seed = {"story_id": story_id, "record_key": record_key, "subject": subject}
            briefs.append(
                {
                    "asset_request_id": _stable_id("request", seed),
                    "story_id": story_id,
                    "beat_ids": [],
                    "visual_goal": "show_it",
                    "purpose": "Give the story one real source-owned visual anchor.",
                    "subject": subject,
                    "requested_asset_types": ["source_page", "source_image"],
                    "must_show": [subject] if subject else [],
                    "must_avoid": [],
                    "preferred_record_keys": [record_key] if record_key else [],
                    "search_queries": [],
                    "brief_source": "script_story_asset_hint",
                }
            )
    return briefs


def _normalized_asset_types(value: Any) -> list[str]:
    aliases = {
        "source": "source_page",
        "article": "source_page",
        "source_page": "source_page",
        "source_image": "source_image",
        "hero_image": "source_image",
        "source_video": "source_video",
        "product_ui": "official_product_interface",
        "interface": "official_product_interface",
        "logo": "logo",
        "photo": "context_photo",
        "image": "context_photo",
        "video": "source_video",
        "broll": "source_video",
        "figure": "source_figure",
        "chart": "code_graphic",
        "diagram": "code_graphic",
        "kinetic_text": "kinetic_text",
    }
    return dedupe([aliases.get(clean_text(item).lower(), clean_text(item).lower()) for item in _text_list(value)])


def _text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [clean_text(value)] if clean_text(value) else []
    if not isinstance(value, list):
        return []
    return dedupe([clean_text(item) for item in value])


def _source_page_asset(
    story_id: str,
    record: dict[str, Any],
    *,
    beat_targets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    record_key = clean_text(record.get("record_key"))
    url = first_url(record)
    literal_beat_targets = [
        item
        for item in (beat_targets or [])
        if clean_text(item.get("source_field")) != "semantic_source_brief"
    ]
    return {
        "asset_id": _stable_id("source_page", {"record_key": record_key, "url": url}),
        "story_id": story_id,
        "asset_type": "source_page",
        "status": "available",
        "review_status": "trusted_source",
        "source_record_key": record_key,
        "source_url": url,
        "asset_url": url,
        "local_path": "",
        "title": clean_text(record.get("title")),
        "description": clean_text(record.get("summary") or record.get("description")),
        "source_name": clean_text(record.get("source_name") or record.get("source")),
        "screenshot_target_candidates": dedupe(
            [
                *[
                    clean_text(item.get("source_text"))
                    for item in literal_beat_targets
                    if clean_text(item.get("source_text"))
                ],
                *screenshot_target_candidates(record),
            ]
        )[:12],
        "beat_screenshot_targets": literal_beat_targets,
        "provenance_class": "selected_story_record",
    }


def _collect_source_media(
    records: list[tuple[str, dict[str, Any]]],
    *,
    image_output_dir: Path,
    video_output_dir: Path,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    if not records:
        return []
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(int(config["worker_count"]), len(records))) as executor:
        future_to_record = {
            executor.submit(
                _source_media_for_record,
                story_id,
                record,
                image_output_dir,
                video_output_dir,
                config,
            ): (story_id, record)
            for story_id, record in records
        }
        for future in as_completed(future_to_record):
            story_id, record = future_to_record[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(
                    {
                        "warning": (
                            f"{story_id}/{clean_text(record.get('record_key'))}: "
                            f"source metadata collection failed: {type(exc).__name__}: {exc}"
                        )
                    }
                )
    return results


def _source_media_for_record(
    story_id: str,
    record: dict[str, Any],
    image_output_dir: Path,
    video_output_dir: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    source_url = first_url(record)
    record_key = clean_text(record.get("record_key"))
    response = requests.get(
        source_url,
        headers={"User-Agent": config["user_agent"]},
        timeout=int(config["request_timeout_seconds"]),
        stream=True,
    )
    response.raise_for_status()
    content_type = clean_text(response.headers.get("Content-Type")).lower()
    if "html" not in content_type:
        return {"warning": f"{story_id}/{record_key}: selected source is not an HTML page"}
    html_bytes = _bounded_response_bytes(response, int(config["max_html_bytes"]))
    parser = _MetadataParser()
    parser.feed(html_bytes.decode(response.encoding or "utf-8", errors="replace"))
    hero_url = clean_text(
        parser.metadata.get("og:image:secure_url")
        or parser.metadata.get("og:image")
        or parser.metadata.get("twitter:image")
        or parser.metadata.get("twitter:image:src")
        or parser.metadata.get("image_src")
    )
    candidates: list[dict[str, Any]] = []
    if hero_url:
        candidates.append(
            {
                "url": hero_url,
                "alt": clean_text(parser.metadata.get("og:image:alt")),
                "title": clean_text(parser.metadata.get("og:title")),
                "declared_width": _optional_int(parser.metadata.get("og:image:width")),
                "declared_height": _optional_int(parser.metadata.get("og:image:height")),
                "image_role": "source_hero",
            }
        )
    candidates.extend(parser.image_candidates)

    all_unique_candidates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for candidate in candidates:
        image_url = urljoin(response.url, clean_text(candidate.get("url")))
        parsed = urlparse(image_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        signature = image_url.casefold()
        if signature in seen_urls:
            continue
        seen_urls.add(signature)
        all_unique_candidates.append({**candidate, "url": image_url})
    unique_candidates = all_unique_candidates[: int(config["max_image_candidates"])]

    assets: list[dict[str, Any]] = []
    warnings: list[str] = []
    image_assets: list[dict[str, Any]] = []
    evaluated_image_candidate_count = 0
    if config.get("collect_source_images", True):
        for candidate_order, candidate in enumerate(unique_candidates, start=1):
            if len(image_assets) >= int(config["max_images_per_record"]):
                break
            evaluated_image_candidate_count += 1
            try:
                asset = _download_source_image_candidate(
                    story_id=story_id,
                    record=record,
                    source_url=response.url,
                    candidate=candidate,
                    candidate_order=candidate_order,
                    parser=parser,
                    output_dir=image_output_dir,
                    config=config,
                )
            except Exception as exc:
                warnings.append(
                    f"{story_id}/{record_key}: image candidate {candidate_order} rejected: "
                    f"{type(exc).__name__}: {exc}"
                )
                continue
            if _is_near_duplicate_image(
                asset,
                image_assets,
                max_distance=int(config["near_duplicate_hash_distance"]),
            ):
                Path(clean_text(asset.get("local_path"))).unlink(missing_ok=True)
                warnings.append(
                    f"{story_id}/{record_key}: image candidate {candidate_order} rejected as near-duplicate"
                )
                continue
            image_assets.append(asset)
        assets.extend(image_assets)

    video_candidates = _video_candidates(parser, response.url, config)
    linked_video_candidates = _source_linked_video_candidates(
        parser=parser,
        page_url=response.url,
        record=record,
        config=config.get("source_linked_video") or {},
    )
    video_assets: list[dict[str, Any]] = []
    if config.get("collect_source_videos", False):
        for candidate_order, candidate in enumerate(video_candidates, start=1):
            if len(video_assets) >= int(config["max_videos_per_record"]):
                break
            try:
                video_assets.append(
                    _download_source_video_candidate(
                        story_id=story_id,
                        record=record,
                        source_url=response.url,
                        candidate=candidate,
                        candidate_order=candidate_order,
                        parser=parser,
                        output_dir=video_output_dir,
                        config=config,
                    )
                )
            except Exception as exc:
                warnings.append(
                    f"{story_id}/{record_key}: video candidate {candidate_order} rejected: "
                    f"{type(exc).__name__}: {exc}"
                )
        linked_config = config.get("source_linked_video") or {}
        if linked_config.get("enabled", False) and len(video_assets) < int(
            config["max_videos_per_record"]
        ):
            for candidate_order, candidate in enumerate(linked_video_candidates, start=1):
                if len(video_assets) >= int(config["max_videos_per_record"]):
                    break
                try:
                    video_assets.append(
                        _download_source_linked_video_candidate(
                            story_id=story_id,
                            record=record,
                            source_url=response.url,
                            candidate=candidate,
                            candidate_order=candidate_order,
                            output_dir=video_output_dir,
                            page_config=config,
                            linked_config=linked_config,
                        )
                    )
                except Exception as exc:
                    warnings.append(
                        f"{story_id}/{record_key}: linked video candidate {candidate_order} "
                        f"rejected: {type(exc).__name__}: {exc}"
                    )
        assets.extend(video_assets)

    if not assets:
        requested = []
        if config.get("collect_source_images", True):
            requested.append("image")
        if config.get("collect_source_videos", False):
            requested.append("video")
        return {
            "warning": (
                f"{story_id}/{record_key}: no {' or '.join(requested) or 'media'} candidate "
                "met the configured structural requirements"
            ),
            "warnings": warnings,
            "candidate_telemetry": _source_candidate_telemetry(
                story_id=story_id,
                record_key=record_key,
                source_url=response.url,
                discovered_count=len(candidates),
                unique_count=len(all_unique_candidates),
                candidate_pool_count=len(unique_candidates),
                evaluated_count=evaluated_image_candidate_count,
                retained_count=len(image_assets),
            ),
        }
    return {
        "assets": assets,
        "warnings": warnings,
        "candidate_telemetry": _source_candidate_telemetry(
            story_id=story_id,
            record_key=record_key,
            source_url=response.url,
            discovered_count=len(candidates),
            unique_count=len(all_unique_candidates),
            candidate_pool_count=len(unique_candidates),
            evaluated_count=evaluated_image_candidate_count,
            retained_count=len(image_assets),
        ),
    }


def _source_candidate_telemetry(
    *,
    story_id: str,
    record_key: str,
    source_url: str,
    discovered_count: int,
    unique_count: int,
    candidate_pool_count: int,
    evaluated_count: int,
    retained_count: int,
) -> dict[str, Any]:
    return {
        "story_id": story_id,
        "record_key": record_key,
        "source_url": source_url,
        "ordering": "declared_source_hero_then_document_order",
        "semantic_reranking_applied": False,
        "image_candidates_discovered": discovered_count,
        "image_candidates_unique": unique_count,
        "image_candidates_in_resource_pool": candidate_pool_count,
        "image_candidates_evaluated": evaluated_count,
        "image_candidates_retained": retained_count,
        "image_candidates_unevaluated_due_to_candidate_limit": max(
            0, unique_count - candidate_pool_count
        ),
        "image_candidates_unevaluated_due_to_retention_limit": max(
            0, candidate_pool_count - evaluated_count
        ),
    }


def _aggregate_candidate_telemetry(items: list[dict[str, Any]]) -> dict[str, Any]:
    count_fields = (
        "image_candidates_discovered",
        "image_candidates_unique",
        "image_candidates_in_resource_pool",
        "image_candidates_evaluated",
        "image_candidates_retained",
        "image_candidates_unevaluated_due_to_candidate_limit",
        "image_candidates_unevaluated_due_to_retention_limit",
    )
    return {
        "source_record_candidate_telemetry": items,
        **{
            field: sum(int(item.get(field, 0)) for item in items)
            for field in count_fields
        },
    }


def _video_candidates(
    parser: _MetadataParser,
    page_url: str,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    metadata_url = clean_text(
        parser.metadata.get("og:video:secure_url")
        or parser.metadata.get("og:video:url")
        or parser.metadata.get("og:video")
        or parser.metadata.get("twitter:player:stream")
    )
    if metadata_url:
        candidates.append(
            {
                "url": metadata_url,
                "mime_type": clean_text(
                    parser.metadata.get("og:video:type")
                    or parser.metadata.get("twitter:player:stream:content_type")
                ),
                "video_role": "source_hero_video",
            }
        )
    candidates.extend(parser.video_candidates)

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        video_url = urljoin(page_url, clean_text(candidate.get("url")))
        parsed = urlparse(video_url)
        suffix = Path(parsed.path).suffix.lower()
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or suffix in {".m3u8", ".mpd"}
        ):
            continue
        signature = video_url.casefold()
        if signature in seen:
            continue
        seen.add(signature)
        unique.append({**candidate, "url": video_url})
        if len(unique) >= int(config["max_video_candidates"]):
            break
    return unique


def _source_video_provider(url: str) -> str:
    parsed = urlparse(clean_text(url))
    host = parsed.netloc.casefold().split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    if host in {"youtube.com", "m.youtube.com", "youtu.be", "youtube-nocookie.com"}:
        return "youtube"
    if host in {"vimeo.com", "player.vimeo.com"}:
        return "vimeo"
    if host in {"x.com", "mobile.x.com", "twitter.com", "mobile.twitter.com"}:
        return "x"
    return ""


def _source_linked_video_candidates(
    *,
    parser: _MetadataParser,
    page_url: str,
    record: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    if not config.get("enabled", False):
        return []
    allowed_providers = {
        clean_text(provider).casefold() for provider in config.get("providers", [])
    }
    raw_candidates: list[dict[str, Any]] = [
        {
            "url": page_url,
            "provider": _source_video_provider(page_url),
            "video_role": "selected_record_video_page",
        },
        *parser.linked_video_candidates,
    ]
    for metadata_key in ("og:video", "og:video:url", "twitter:player"):
        metadata_url = clean_text(parser.metadata.get(metadata_key))
        raw_candidates.append(
            {
                "url": metadata_url,
                "provider": _source_video_provider(metadata_url),
                "video_role": "source_page_video_metadata",
            }
        )
    for field in ("url", "canonical_url", "source_url"):
        record_url = clean_text(record.get(field))
        raw_candidates.append(
            {
                "url": record_url,
                "provider": _source_video_provider(record_url),
                "video_role": "selected_record_video_page",
            }
        )

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in raw_candidates:
        candidate_url = urljoin(page_url, clean_text(candidate.get("url")))
        provider = clean_text(candidate.get("provider")) or _source_video_provider(candidate_url)
        parsed = urlparse(candidate_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or provider not in allowed_providers
        ):
            continue
        signature = candidate_url.casefold().rstrip("/")
        if signature in seen:
            continue
        seen.add(signature)
        unique.append({**candidate, "url": candidate_url, "provider": provider})
        if len(unique) >= int(config.get("max_links_per_record", 3)):
            break
    return unique


def _download_source_linked_video_candidate(
    *,
    story_id: str,
    record: dict[str, Any],
    source_url: str,
    candidate: dict[str, Any],
    candidate_order: int,
    output_dir: Path,
    page_config: dict[str, Any],
    linked_config: dict[str, Any],
) -> dict[str, Any]:
    provider_url = clean_text(candidate.get("url"))
    provider = clean_text(candidate.get("provider"))
    executable = clean_text(linked_config.get("yt_dlp_path")) or "yt-dlp"
    resolved_executable = shutil.which(executable)
    if not resolved_executable:
        raise FileNotFoundError(f"source-linked video resolver not found: {executable}")

    timeout_seconds = int(linked_config.get("download_timeout_seconds", 180))
    metadata_process = subprocess.run(
        [
            resolved_executable,
            "--dump-single-json",
            "--skip-download",
            "--no-playlist",
            provider_url,
        ],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if metadata_process.returncode != 0:
        detail = clean_text(metadata_process.stderr or metadata_process.stdout)
        raise RuntimeError(f"provider metadata lookup failed: {detail[:500]}")
    try:
        metadata = json.loads(metadata_process.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("provider metadata lookup returned invalid JSON") from exc

    duration_seconds = float(metadata.get("duration") or 0.0)
    max_duration_seconds = int(linked_config.get("max_duration_seconds", 1_800))
    if duration_seconds > max_duration_seconds:
        raise ValueError(
            f"provider video duration {duration_seconds:.1f}s exceeds configured "
            f"limit of {max_duration_seconds}s"
        )

    asset_id = _stable_id(
        "source_video",
        {
            "record_key": clean_text(record.get("record_key")),
            "provider_url": provider_url,
        },
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = output_dir / f"{asset_id}.%(ext)s"
    max_height = int(linked_config.get("max_height", 1_080))
    max_video_bytes = int(page_config["max_video_bytes"])
    download_process = subprocess.run(
        [
            resolved_executable,
            "--no-playlist",
            "--no-progress",
            "--no-warnings",
            "--max-filesize",
            str(max_video_bytes),
            "--match-filter",
            f"duration <= {max_duration_seconds}",
            "--format",
            (
                f"bestvideo[height<={max_height}][ext=mp4]/"
                f"best[height<={max_height}][ext=mp4]/"
                f"bestvideo[height<={max_height}]/best[height<={max_height}]"
            ),
            "--output",
            str(output_template),
            provider_url,
        ],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if download_process.returncode != 0:
        detail = clean_text(download_process.stderr or download_process.stdout)
        raise RuntimeError(f"provider video download failed: {detail[:500]}")
    output_candidates = sorted(
        path
        for path in output_dir.glob(f"{asset_id}.*")
        if path.suffix.lower() in {".mp4", ".webm", ".mov", ".m4v"}
        and path.is_file()
        and path.stat().st_size > 0
    )
    if len(output_candidates) != 1:
        raise RuntimeError(
            f"provider video resolver produced {len(output_candidates)} usable files"
        )
    output_path = output_candidates[0]
    if output_path.stat().st_size > max_video_bytes:
        output_path.unlink(missing_ok=True)
        raise ValueError(f"downloaded video exceeds configured limit of {max_video_bytes} bytes")

    try:
        probe = _probe_video(
            output_path,
            clean_text(page_config.get("ffprobe_path")) or "ffprobe",
        )
        width = int(probe["width"])
        height = int(probe["height"])
        probed_duration = float(probe["duration_seconds"])
        if width < int(page_config["min_video_width"]) or height < int(
            page_config["min_video_height"]
        ):
            raise ValueError(f"video is too small ({width}x{height})")
        if probed_duration <= 0:
            raise ValueError("video duration is not positive")
    except Exception:
        output_path.unlink(missing_ok=True)
        raise

    return {
        "asset_id": asset_id,
        "story_id": story_id,
        "asset_type": "source_video",
        "status": "available",
        "review_status": "trusted_source",
        "source_record_key": clean_text(record.get("record_key")),
        "source_url": source_url,
        "asset_url": provider_url,
        "local_path": str(output_path),
        "content_sha256": file_sha256(output_path),
        "mime_type": _content_type_for_video(output_path),
        "title": clean_text(metadata.get("title") or record.get("title")),
        "description": clean_text(metadata.get("description") or record.get("summary")),
        "video_role": clean_text(candidate.get("video_role")) or "source_page_linked_video",
        "candidate_order": candidate_order,
        "source_name": clean_text(record.get("source_name") or record.get("source")),
        "provider": provider,
        "provider_id": clean_text(metadata.get("id")),
        "uploader": clean_text(metadata.get("uploader") or metadata.get("channel")),
        "width": width,
        "height": height,
        "aspect_ratio": round(width / height, 4),
        "duration_seconds": round(probed_duration, 3),
        "provenance_class": "selected_source_page_linked_video",
        "provenance_trust": {
            "status": "trusted",
            "basis": "linked_from_selected_story_source",
        },
        "narration_suitability": {
            "status": "unreviewed",
            "basis": "planner_must_match_asset_to_active_script_beat",
        },
    }


def _download_source_image_candidate(
    *,
    story_id: str,
    record: dict[str, Any],
    source_url: str,
    candidate: dict[str, Any],
    candidate_order: int,
    parser: _MetadataParser,
    output_dir: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    declared_width = candidate.get("declared_width")
    declared_height = candidate.get("declared_height")
    if (
        isinstance(declared_width, int)
        and isinstance(declared_height, int)
        and not _image_dimensions_are_usable(declared_width, declared_height, config)
    ):
        raise ValueError(f"declared image is too small ({declared_width}x{declared_height})")

    image_url = clean_text(candidate.get("url"))
    image_response = requests.get(
        image_url,
        headers={"User-Agent": config["user_agent"], "Referer": source_url},
        timeout=int(config["request_timeout_seconds"]),
        stream=True,
    )
    image_response.raise_for_status()
    image_bytes = _bounded_response_bytes(image_response, int(config["max_image_bytes"]))
    with Image.open(io.BytesIO(image_bytes)) as image:
        image.load()
        image = ImageOps.exif_transpose(image)
        width, height = image.size
        if not _image_dimensions_are_usable(width, height, config):
            raise ValueError(f"image is too small ({width}x{height})")
        aspect_ratio = width / height if height else 0.0
        if (
            aspect_ratio < float(config["min_image_aspect_ratio"])
            or aspect_ratio > float(config["max_image_aspect_ratio"])
        ):
            raise ValueError(
                f"image aspect ratio {aspect_ratio:.2f} is outside the configured range"
            )
        perceptual_hash = _difference_hash(image)
        asset_id = _stable_id(
            "source_image",
            {"record_key": clean_text(record.get("record_key")), "image_url": image_url},
        )
        has_alpha = "A" in image.getbands()
        output_path = output_dir / f"{asset_id}{'.png' if has_alpha else '.jpg'}"
        if has_alpha:
            image.save(output_path, format="PNG", optimize=True)
        else:
            image.convert("RGB").save(output_path, format="JPEG", quality=92, optimize=True)

    alt_text = clean_text(candidate.get("alt"))
    candidate_title = clean_text(candidate.get("title"))
    page_title = clean_text(parser.metadata.get("og:title") or record.get("title"))
    page_description = clean_text(
        parser.metadata.get("og:description")
        or parser.metadata.get("description")
        or record.get("summary")
        or record.get("description")
    )
    description = clean_text(" ".join(item for item in (alt_text, candidate_title, page_description) if item))
    return {
        "asset_id": asset_id,
        "story_id": story_id,
        "asset_type": "source_image",
        "status": "available",
        "review_status": "trusted_source",
        "source_record_key": clean_text(record.get("record_key")),
        "source_url": source_url,
        "asset_url": image_url,
        "local_path": str(output_path),
        "content_sha256": file_sha256(output_path),
        "title": alt_text or candidate_title or page_title,
        "description": description,
        "alt_text": alt_text,
        "image_role": clean_text(candidate.get("image_role")) or "article_image",
        "candidate_order": candidate_order,
        "source_name": clean_text(record.get("source_name") or record.get("source")),
        "width": width,
        "height": height,
        "aspect_ratio": round(width / height, 4),
        "perceptual_hash": perceptual_hash,
        "provenance_class": "selected_source_page_image",
    }


def _image_dimensions_are_usable(
    width: int,
    height: int,
    config: dict[str, Any],
) -> bool:
    return (
        min(width, height) >= int(config["min_image_short_edge"])
        and width * height >= int(config["min_image_pixel_area"])
    )


def _download_source_video_candidate(
    *,
    story_id: str,
    record: dict[str, Any],
    source_url: str,
    candidate: dict[str, Any],
    candidate_order: int,
    parser: _MetadataParser,
    output_dir: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    video_url = clean_text(candidate.get("url"))
    video_response = requests.get(
        video_url,
        headers={"User-Agent": config["user_agent"], "Referer": source_url},
        timeout=int(config["request_timeout_seconds"]),
        stream=True,
    )
    video_response.raise_for_status()
    content_type = clean_text(video_response.headers.get("Content-Type")).split(";", 1)[0].lower()
    suffix = _video_suffix(video_url, content_type)
    if not suffix:
        raise ValueError(f"remote candidate is not a direct supported video ({content_type or 'unknown type'})")

    asset_id = _stable_id(
        "source_video",
        {"record_key": clean_text(record.get("record_key")), "video_url": video_url},
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{asset_id}{suffix}"
    _write_bounded_response(
        video_response,
        output_path,
        int(config["max_video_bytes"]),
    )
    try:
        probe = _probe_video(output_path, clean_text(config.get("ffprobe_path")) or "ffprobe")
        width = int(probe["width"])
        height = int(probe["height"])
        duration_seconds = float(probe["duration_seconds"])
        if width < int(config["min_video_width"]) or height < int(config["min_video_height"]):
            raise ValueError(f"video is too small ({width}x{height})")
        if duration_seconds <= 0:
            raise ValueError("video duration is not positive")
    except Exception:
        output_path.unlink(missing_ok=True)
        raise

    page_title = clean_text(parser.metadata.get("og:title") or record.get("title"))
    page_description = clean_text(
        parser.metadata.get("og:description")
        or parser.metadata.get("description")
        or record.get("summary")
        or record.get("description")
    )
    return {
        "asset_id": asset_id,
        "story_id": story_id,
        "asset_type": "source_video",
        "status": "available",
        "review_status": "trusted_source",
        "source_record_key": clean_text(record.get("record_key")),
        "source_url": source_url,
        "asset_url": video_url,
        "local_path": str(output_path),
        "content_sha256": file_sha256(output_path),
        "mime_type": content_type or _content_type_for_video(output_path),
        "title": page_title,
        "description": page_description,
        "video_role": clean_text(candidate.get("video_role")) or "source_page_video",
        "candidate_order": candidate_order,
        "source_name": clean_text(record.get("source_name") or record.get("source")),
        "width": width,
        "height": height,
        "aspect_ratio": round(width / height, 4),
        "duration_seconds": round(duration_seconds, 3),
        "provenance_class": "selected_source_page_video",
    }


def _video_suffix(url: str, content_type: str) -> str:
    by_type = {
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "video/x-m4v": ".m4v",
    }
    if content_type in by_type:
        return by_type[content_type]
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in {".mp4", ".webm", ".mov", ".m4v"} else ""


def _content_type_for_video(path: Path) -> str:
    return {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".m4v": "video/x-m4v",
    }.get(path.suffix.lower(), "application/octet-stream")


def _write_bounded_response(response: requests.Response, output_path: Path, limit: int) -> None:
    declared = response.headers.get("Content-Length")
    if declared:
        try:
            declared_size = int(declared)
        except (TypeError, ValueError):
            declared_size = 0
        if declared_size > limit:
            raise ValueError(f"remote payload exceeds configured limit of {limit} bytes")
    total = 0
    try:
        with output_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=262_144):
                if not chunk:
                    continue
                total += len(chunk)
                if total > limit:
                    raise ValueError(f"remote payload exceeds configured limit of {limit} bytes")
                handle.write(chunk)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    if total <= 0:
        output_path.unlink(missing_ok=True)
        raise ValueError("remote video payload is empty")


def _probe_video(path: Path, ffprobe_path: str) -> dict[str, Any]:
    completed = subprocess.run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,duration:format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise ValueError((completed.stderr or "ffprobe failed")[-1000:])
    data = json.loads(completed.stdout or "{}")
    streams = data.get("streams") if isinstance(data, dict) else []
    if not streams or not isinstance(streams[0], dict):
        raise ValueError("video has no usable video stream")
    stream = streams[0]
    duration = stream.get("duration") or (data.get("format") or {}).get("duration")
    return {
        "width": int(float(stream.get("width") or 0)),
        "height": int(float(stream.get("height") or 0)),
        "duration_seconds": float(duration or 0),
    }


def _difference_hash(image: Image.Image) -> str:
    grayscale = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(grayscale.get_flattened_data())
    bits = []
    for row in range(8):
        offset = row * 9
        bits.extend(pixels[offset + column] > pixels[offset + column + 1] for column in range(8))
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:016x}"


def _hash_distance(first: str, second: str) -> int:
    try:
        return (int(first, 16) ^ int(second, 16)).bit_count()
    except (TypeError, ValueError):
        return 65


def _is_near_duplicate_image(
    candidate: dict[str, Any],
    existing: list[dict[str, Any]],
    *,
    max_distance: int,
) -> bool:
    candidate_hash = clean_text(candidate.get("perceptual_hash"))
    if not candidate_hash:
        return False
    return any(
        _hash_distance(candidate_hash, clean_text(asset.get("perceptual_hash"))) <= max_distance
        for asset in existing
        if clean_text(asset.get("perceptual_hash"))
    )


def _bounded_response_bytes(response: requests.Response, limit: int) -> bytes:
    declared = response.headers.get("Content-Length")
    if declared:
        try:
            declared_size = int(declared)
        except (TypeError, ValueError):
            declared_size = 0
        if declared_size > limit:
            raise ValueError(f"remote payload exceeds configured limit of {limit} bytes")
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > limit:
            raise ValueError(f"remote payload exceeds configured limit of {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def _logo_assets_for_story(
    story: dict[str, Any],
    script_hint: dict[str, Any],
    *,
    asset_briefs: list[dict[str, Any]] | None = None,
    local_logo_dir: Path | None,
) -> list[dict[str, Any]]:
    story_id = clean_text(story.get("story_id"))
    identity = story.get("story_identity") if isinstance(story.get("story_identity"), dict) else {}
    entities = dedupe(
        [
            clean_text(identity.get("primary_entity")),
            clean_text(identity.get("owning_org")),
            *[clean_text(item) for item in script_hint.get("logo_entities", [])],
            *_logo_entities_from_asset_briefs(asset_briefs or []),
        ]
    )
    assets: list[dict[str, Any]] = []
    for entity in entities:
        local_path = _local_logo_path(entity, local_logo_dir)
        simple_icon = simple_icon_export_for(entity)
        if not local_path and not simple_icon:
            continue
        assets.append(
            {
                "asset_id": _stable_id("logo", {"story_id": story_id, "entity": entity}),
                "story_id": story_id,
                "asset_type": "logo",
                "status": "available",
                "review_status": "trusted_identity",
                "source_record_key": "",
                "source_url": "",
                "asset_url": "",
                "local_path": str(local_path) if local_path else "",
                "content_sha256": file_sha256(local_path) if local_path else "",
                "title": entity,
                "description": f"Resolvable identity asset for {entity}",
                "source_name": "local_override" if local_path else "simple-icons",
                "simple_icon_export": simple_icon or "",
                "provenance_class": "local_override" if local_path else "simple_icons",
            }
        )
    return assets


def _logo_entities_from_asset_briefs(briefs: list[dict[str, Any]]) -> list[str]:
    entities: list[str] = []
    for brief in briefs:
        if not isinstance(brief, dict) or "logo" not in set(brief.get("requested_asset_types", [])):
            continue
        candidates = [clean_text(brief.get("subject")), *[clean_text(item) for item in brief.get("must_show", [])]]
        for candidate in candidates:
            candidate = candidate.removesuffix(" logo").removesuffix(" Logo").strip()
            if candidate:
                entities.append(candidate)
    return dedupe(entities)


def _local_logo_path(entity: str, directory: Path | None) -> Path | None:
    if not directory or not directory.exists():
        return None
    stem = slugify(entity)
    for extension in ("svg", "png", "jpg", "jpeg", "webp"):
        path = directory / f"{stem}.{extension}"
        if path.exists() and path.is_file():
            return path
    return None


def _bind_brief_to_assets(brief: dict[str, Any], assets: list[dict[str, Any]]) -> dict[str, Any]:
    item = dict(brief)
    requested_types = set(brief.get("requested_asset_types", []))
    record_keys = set(brief.get("preferred_record_keys", []))
    matched = []
    for asset in assets:
        asset_type = clean_text(asset.get("asset_type"))
        source_key = clean_text(asset.get("source_record_key"))
        compatible_types = {asset_type}
        if asset_type == "source_video":
            compatible_types.add("broll_video")
        if not compatible_types & requested_types:
            continue
        if record_keys and source_key and source_key not in record_keys:
            continue
        matched.append(clean_text(asset.get("asset_id")))
    item["matched_asset_ids"] = dedupe(matched)
    if matched:
        item["resolution_status"] = "available"
    elif requested_types <= {"code_graphic", "kinetic_text", "transition"}:
        item["resolution_status"] = "no_external_asset_required"
    else:
        item["resolution_status"] = "unresolved"
    return item


def _dedupe_assets(
    assets: list[dict[str, Any]],
    *,
    near_duplicate_hash_distance: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    seen: set[str] = set()
    seen_story_image_hashes: set[tuple[str, str]] = set()
    perceptual_hashes_by_story: dict[str, list[str]] = {}
    kept: list[dict[str, Any]] = []
    duplicate_asset_id_count = 0
    exact_duplicate_image_count = 0
    near_duplicate_image_count = 0
    for asset in assets:
        asset_id = clean_text(asset.get("asset_id"))
        if not asset_id or asset_id in seen:
            if asset_id in seen:
                duplicate_asset_id_count += 1
            continue
        if clean_text(asset.get("asset_type")) == "source_image":
            image_signature = (
                clean_text(asset.get("story_id")),
                clean_text(asset.get("content_sha256")),
            )
            if image_signature[1] and image_signature in seen_story_image_hashes:
                exact_duplicate_image_count += 1
                continue
            if image_signature[1]:
                seen_story_image_hashes.add(image_signature)
            story_id = clean_text(asset.get("story_id"))
            perceptual_hash = clean_text(asset.get("perceptual_hash"))
            if perceptual_hash and any(
                _hash_distance(perceptual_hash, existing_hash)
                <= near_duplicate_hash_distance
                for existing_hash in perceptual_hashes_by_story.get(story_id, [])
            ):
                duplicate_path = clean_text(asset.get("local_path"))
                if duplicate_path:
                    Path(duplicate_path).unlink(missing_ok=True)
                near_duplicate_image_count += 1
                continue
            if perceptual_hash:
                perceptual_hashes_by_story.setdefault(story_id, []).append(perceptual_hash)
        seen.add(asset_id)
        kept.append(asset)
    return kept, {
        "duplicate_asset_id_count": duplicate_asset_id_count,
        "exact_duplicate_image_count": exact_duplicate_image_count,
        "near_duplicate_image_count": near_duplicate_image_count,
    }


def _build_contact_sheet(
    assets: list[dict[str, Any]],
    output_path: Path,
    config: dict[str, Any],
) -> Path | None:
    if not config.get("enabled") or not assets:
        return None
    valid_assets = [asset for asset in assets if Path(clean_text(asset.get("local_path"))).exists()]
    if not valid_assets:
        return None
    columns = int(config["columns"])
    tile_width = int(config["tile_width"])
    tile_height = int(config["tile_height"])
    label_height = 52
    rows = math.ceil(len(valid_assets) / columns)
    sheet = Image.new("RGB", (columns * tile_width, rows * (tile_height + label_height)), "#07101a")
    draw = ImageDraw.Draw(sheet)
    for index, asset in enumerate(valid_assets):
        x = (index % columns) * tile_width
        y = (index // columns) * (tile_height + label_height)
        with Image.open(clean_text(asset.get("local_path"))) as image:
            tile = ImageOps.fit(image.convert("RGB"), (tile_width, tile_height), method=Image.Resampling.LANCZOS)
        sheet.paste(tile, (x, y))
        label = clean_text(asset.get("title"))[:70]
        draw.rectangle((x, y + tile_height, x + tile_width, y + tile_height + label_height), fill="#101d2d")
        draw.text((x + 12, y + tile_height + 10), label, fill="#f7fbff")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, quality=88)
    return output_path


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    fingerprint = artifact_fingerprint(payload).removeprefix("sha256:")[:14]
    return f"asset_{prefix}_{fingerprint}"
