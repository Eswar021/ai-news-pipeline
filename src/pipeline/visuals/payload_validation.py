from __future__ import annotations

from copy import deepcopy
from typing import Any

from .common import clean_text
from .recipes import ACTIVE_RENDER_KINDS, validate_scene_recipe


SOURCE_ARTICLE_KINDS = {"source_article_scene", "quote_or_claim_highlight_scene"}
SOURCE_BOUND_KINDS = SOURCE_ARTICLE_KINDS | {"browser_walkthrough_scene"}
MEDIA_KINDS = {"context_image_scene", "broll_video_scene"}
HEADLINE_KINDS = {
    "editorial_text_scene",
    "simple_explainer_scene",
    "story_transition_scene",
    "browser_walkthrough_scene",
    "document_stack_scene",
    "interface_transform_scene",
}
SUPPORTED_RENDER_KINDS = set(ACTIVE_RENDER_KINDS)


# These are provider-facing descriptions of the renderer contract. The
# capability allowlist and editorial guidance remain config-driven, while the
# structural payload shape stays next to the validator that enforces it.
PROMPT_PAYLOAD_CONTRACTS: dict[str, dict[str, Any]] = {
    "source_article_scene": {
        "required": {
            "url": "absolute selected-story http(s) URL",
            "source_record_key": "exact selected-story record key",
            "target_text": "exact supplied screenshot_target_candidates value",
            "highlight_phrases": "list[str] copied from the active narration or target text",
            "crop_strategy": "article_viewport | headline_then_body | target_text_focus",
            "overlay_headline": "short string",
            "motion_style": "slow_push | highlight_scan | browser_zoom",
        },
        "optional": {
            "asset_id": "exact available source_page asset ID",
        },
    },
    "context_image_scene": {
        "required": {
            "asset_id": "exact available source_image, official_product_interface, or source_figure asset ID",
            "shot_style": "wide | medium | detail",
            "overlay_headline": "short string; may be empty when show_overlay is false",
            "motion_style": "slow_push | gentle_pan | detail_zoom",
            "show_overlay": "boolean",
        },
        "optional": {
            "annotations": "list of 1-3 short callouts supported by the active narration",
        },
    },
    "broll_video_scene": {
        "required": {
            "shot_style": "wide | medium | detail",
            "overlay_headline": "short string; may be empty when show_overlay is false",
            "motion_style": "editorial_crop | gentle_pan | detail_zoom",
            "show_overlay": "boolean",
        },
        "optional": {
            "asset_id": "exact available source_video asset ID",
            "video_moment_id": "exact video_moments[].video_moment_id from the selected source_video asset",
            "clip_selection_reason": "short explanation of why this exact video moment fits the active narration beat",
            "annotations": "list of 1-3 short callouts supported by the active narration",
            "search_queries": "list[str] used only when deliberate external discovery is enabled",
            "must_show": "list[str] used only when deliberate external discovery is enabled",
            "must_avoid": "list[str] used only when deliberate external discovery is enabled",
        },
    },
    "logo_reveal_scene": {
        "required": {
            "entities": "list[str] containing one to three supplied entity names",
            "primary_entity": "one exact supplied entity name",
            "logo_strategy": "simple_icons_then_favicon_then_text | catalog_asset",
            "companion_text": "short string no longer than 90 characters",
            "motion_style": "pop_reveal | slide_stack | spotlight",
        },
        "optional": {
            "asset_id": "exact available logo asset ID",
        },
    },
    "editorial_text_scene": {
        "required": {
            "headline": "one concise string no longer than 120 characters",
            "accent_words": "list[str] containing words that appear in headline",
            "composition": "editorial_center | editorial_left | editorial_split",
            "motion_style": "word_reveal | line_wipe | quiet_fade",
        },
        "optional": {
            "eyebrow": "very short string",
            "supporting_text": "one short phrase, not narration copy",
        },
    },
    "simple_explainer_scene": {
        "required": {
            "headline": "one concise string",
            "items": "list of 2-4 objects shaped {label: str, detail?: str}; never a one-item list and never list[str]",
            "orientation": "horizontal | vertical",
            "motion_style": "sequential_focus | connector_reveal | quiet_build",
        },
        "optional": {
            "focus_item_label": "must exactly match one items[].label",
            "connector_label": "short relationship label",
        },
    },
    "story_transition_scene": {
        "required": {
            "headline": "complete canonical story title no longer than 140 characters",
            "accent_words": "list[str] containing words that appear in headline",
            "motion_style": "chapter_wipe | quiet_reveal | editorial_slide",
        },
        "optional": {
            "asset_id": "exact story-owned source image, source video, or logo asset ID",
            "background_media_type": "image | video | logo",
            "background_render_kind": "original LLM-selected opening render kind",
        },
    },
    "quote_or_claim_highlight_scene": {
        "required": {
            "url": "absolute selected-story http(s) URL",
            "source_record_key": "exact selected-story record key",
            "claim_text": "short source-supported claim shown prominently",
            "supporting_text": "exact supporting source phrase or concise beat explanation",
            "target_text": "exact supplied screenshot target",
        },
        "optional": {
            "asset_id": "exact available source_page asset ID",
            "highlight_phrases": "list[str] copied from claim_text or target_text",
            "motion_style": "layered_reveal | highlight_scan | proof_push",
        },
    },
    "browser_walkthrough_scene": {
        "required": {
            "url": "absolute selected-story http(s) URL",
            "source_record_key": "exact selected-story record key",
            "headline": "one concise string",
            "focus_text": "exact supplied screenshot target or interface label",
            "walkthrough_steps": "list of 2-4 objects shaped {label, detail? or target_text?}",
        },
        "optional": {
            "asset_id": "exact available source_page asset ID",
            "motion_style": "guided_focus | cursor_trace | browser_zoom",
        },
    },
    "document_stack_scene": {
        "required": {
            "headline": "one concise string",
            "documents": "list of 1-5 objects shaped {title, source, date?, document_type?, asset_id?, source_record_key?, url?, target_text?}",
            "focus_document_label": "exact documents[].title",
        },
        "optional": {
            "stack_summary": "one short takeaway",
            "motion_style": "evidence_stack | focal_document",
        },
    },
    "interface_transform_scene": {
        "required": {
            "headline": "one concise string",
            "before": "object shaped {label, items: list[str] with at least 2 items}",
            "after": "object shaped {label, items: list[str] with at least 2 items}",
            "transformation_label": "short supported transformation phrase",
        },
        "optional": {"motion_style": "panel_morph | workflow_shift"},
    },
}


def prompt_payload_contract(render_kind: str) -> dict[str, Any]:
    """Return an isolated provider-facing contract for one render kind."""

    return deepcopy(PROMPT_PAYLOAD_CONTRACTS.get(render_kind, {}))


def validate_scene_payload(render_kind: str, payload: dict[str, Any]) -> list[str]:
    """Return structural renderability errors without making editorial judgments."""

    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["payload must be an object"]
    if render_kind not in SUPPORTED_RENDER_KINDS:
        return [f"unsupported render_kind: {render_kind or '<empty>'}"]
    errors.extend(validate_scene_recipe(render_kind, payload))

    if render_kind in HEADLINE_KINDS:
        _require_text(payload, "headline", errors)

    if render_kind in SOURCE_BOUND_KINDS:
        _require_text(payload, "source_record_key", errors)
        url = clean_text(payload.get("url", ""))
        if not url.startswith(("http://", "https://")):
            errors.append("payload.url must be an absolute http(s) URL")

    if render_kind == "source_article_scene":
        _require_text(payload, "target_text", errors)
        _require_text(payload, "overlay_headline", errors)
    elif render_kind == "quote_or_claim_highlight_scene":
        _require_text(payload, "claim_text", errors)
        if not clean_text(payload.get("supporting_text", "")) and not clean_text(payload.get("target_text", "")):
            errors.append("payload.supporting_text or payload.target_text is required")
    elif render_kind in MEDIA_KINDS:
        if clean_text(payload.get("asset_id", "")):
            pass
        else:
            _require_text_list(payload, "search_queries", errors)
            _require_text_list(payload, "must_show", errors)
        if render_kind == "broll_video_scene" and "video_moment_id" in payload:
            _require_text(payload, "video_moment_id", errors)
    elif render_kind == "logo_reveal_scene":
        _require_text(payload, "primary_entity", errors)
        _require_text(payload, "companion_text", errors)
        if len(clean_text(payload.get("companion_text", ""))) > 90:
            errors.append("payload.companion_text must be at most 90 characters for readable rendering")
    elif render_kind == "editorial_text_scene":
        composition = clean_text(payload.get("composition", ""))
        if composition not in {"editorial_center", "editorial_left", "editorial_split"}:
            errors.append(
                "payload.composition must be editorial_center, editorial_left, or editorial_split"
            )
        if len(clean_text(payload.get("headline", ""))) > 120:
            errors.append("payload.headline must be at most 120 characters")
    elif render_kind == "simple_explainer_scene":
        rows = _require_object_rows(payload, "items", errors, minimum=2, required_text=("label",))
        if len(rows) > 4:
            errors.append("payload.items must contain at most 4 items")
        orientation = clean_text(payload.get("orientation", ""))
        if orientation not in {"horizontal", "vertical"}:
            errors.append("payload.orientation must be horizontal or vertical")
        _require_member_label(payload, "focus_item_label", rows, errors, required=False)
    elif render_kind == "story_transition_scene":
        if len(clean_text(payload.get("headline", ""))) > 140:
            errors.append("payload.headline must be at most 140 characters")
        background_type = clean_text(payload.get("background_media_type", ""))
        if background_type and background_type not in {"image", "video", "logo"}:
            errors.append("payload.background_media_type must be image, video, or logo")
        if background_type and not clean_text(payload.get("asset_id", "")):
            errors.append("payload.asset_id is required when background_media_type is set")
    elif render_kind == "browser_walkthrough_scene":
        _require_text(payload, "focus_text", errors)
        _require_object_rows(
            payload,
            "walkthrough_steps",
            errors,
            minimum=2,
            required_text=("label",),
            require_any_text=("detail", "target_text"),
        )
    elif render_kind == "document_stack_scene":
        rows = _require_object_rows(payload, "documents", errors, minimum=1, required_text=("title", "source"))
        focus = clean_text(payload.get("focus_document_label", ""))
        if not focus:
            errors.append("payload.focus_document_label is required")
        elif focus.lower() not in {clean_text(row.get("title", "")).lower() for row in rows}:
            errors.append("payload.focus_document_label must match a document title")
        if clean_text(payload.get("recipe_id")) == "source_proof_montage":
            if len(rows) < 2 or len(rows) > 3:
                errors.append("source_proof_montage requires 2-3 source documents")
            for index, row in enumerate(rows, start=1):
                for field in ("asset_id", "source_record_key", "url"):
                    if not clean_text(row.get(field)):
                        errors.append(
                            f"payload.documents[{index}].{field} is required for source_proof_montage"
                        )
                url = clean_text(row.get("url"))
                if url and not url.startswith(("http://", "https://")):
                    errors.append(
                        f"payload.documents[{index}].url must be an absolute http(s) URL"
                    )
    elif render_kind == "interface_transform_scene":
        _validate_interface_panel(payload, "before", errors)
        _validate_interface_panel(payload, "after", errors)
        _require_text(payload, "transformation_label", errors)
    return errors


def _require_text(payload: dict[str, Any], field: str, errors: list[str]) -> None:
    if not clean_text(payload.get(field, "")):
        errors.append(f"payload.{field} is required")


def _text_values(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [clean_text(item) for item in value if clean_text(item)]


def _require_text_list(
    payload: dict[str, Any],
    field: str,
    errors: list[str],
    *,
    minimum: int = 1,
) -> list[str]:
    values = _text_values(payload.get(field))
    if len(values) < minimum:
        errors.append(f"payload.{field} requires at least {minimum} non-empty text item(s)")
    return values


def _object_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _require_object_rows(
    payload: dict[str, Any],
    field: str,
    errors: list[str],
    *,
    minimum: int,
    required_text: tuple[str, ...],
    require_any_text: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    raw = payload.get(field)
    rows = _object_rows(raw)
    if not isinstance(raw, list) or len(rows) < minimum:
        errors.append(f"payload.{field} requires at least {minimum} object item(s)")
    for index, row in enumerate(rows, start=1):
        for key in required_text:
            if not clean_text(row.get(key, "")):
                errors.append(f"payload.{field}[{index}].{key} is required")
        if require_any_text and not any(clean_text(row.get(key, "")) for key in require_any_text):
            joined = " or ".join(require_any_text)
            errors.append(f"payload.{field}[{index}] requires {joined}")
    return rows


def _require_member_label(
    payload: dict[str, Any],
    field: str,
    rows: list[dict[str, Any]],
    errors: list[str],
    *,
    required: bool,
) -> None:
    value = clean_text(payload.get(field, ""))
    if required and not value:
        errors.append(f"payload.{field} is required")
        return
    labels = {clean_text(row.get("label", "")).lower() for row in rows}
    if value and value.lower() not in labels:
        errors.append(f"payload.{field} must match an item label")


def _validate_interface_panel(payload: dict[str, Any], field: str, errors: list[str]) -> None:
    panel = payload.get(field)
    if not isinstance(panel, dict):
        errors.append(f"payload.{field} must be an object")
        return
    if not clean_text(panel.get("label", "")):
        errors.append(f"payload.{field}.label is required")
    values = _text_values(panel.get("items"))
    if len(values) < 2:
        errors.append(f"payload.{field}.items requires at least 2 non-empty text item(s)")
