from __future__ import annotations

from copy import deepcopy
from typing import Any

from .common import clean_text


RECIPE_REGISTRY: dict[str, dict[str, Any]] = {
    "editorial_hook": {
        "render_kind": "editorial_text_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A complete hook phrase revealed in two deliberate typographic phases with generous whitespace.",
        "best_for": ["intro hooks", "short punchlines", "one clear implication"],
        "avoid_when": ["real media can show the subject", "more than one idea must be explained"],
    },
    "chapter_opener": {
        "render_kind": "story_transition_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A clean story chapter reveal, optionally layered over one verified story-owned visual anchor.",
        "best_for": ["the deterministic first beat of a roundup story"],
        "avoid_when": ["the scene is not a story boundary"],
    },
    "source_proof_scan": {
        "render_kind": "source_article_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A browser-like source proof treatment that moves from headline context to an exact highlighted passage.",
        "best_for": ["source-backed claims", "visible provenance", "article details"],
        "avoid_when": ["the beat is not source-specific", "no exact screenshot target exists"],
    },
    "layered_evidence_reveal": {
        "render_kind": "quote_or_claim_highlight_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A source capture with a restrained evidence strip and sequential phrase highlights, not a quote card.",
        "best_for": ["one consequential statement", "a source sentence that needs emphasis"],
        "avoid_when": ["the words are not present in the selected source"],
    },
    "annotated_image_focus": {
        "render_kind": "context_image_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A strong crop of verified imagery with one or two timed annotation callouts.",
        "best_for": ["hardware", "people", "places", "product imagery", "physical context"],
        "avoid_when": ["the image descriptor does not establish what the image depicts"],
    },
    "annotated_video_focus": {
        "render_kind": "broll_video_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A source-owned video moment with restrained kinetic annotations and editorial reframing.",
        "best_for": ["demos", "robot motion", "interfaces in use", "physical action"],
        "avoid_when": ["the clip does not show the active narration beat"],
    },
    "metric_countup": {
        "render_kind": "data_counter_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "One to three source-supported metrics count into place with clear labels and no dashboard chrome.",
        "best_for": ["funding", "speed", "scale", "percentages", "model size"],
        "avoid_when": ["the exact values are not present in eligible evidence"],
    },
    "metric_contrast": {
        "render_kind": "benchmark_delta_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A before/after or baseline/result contrast whose visual hierarchy lands the delta first.",
        "best_for": ["benchmark deltas", "cost changes", "speedups", "error-rate changes"],
        "avoid_when": ["before, after, or delta values would need to be inferred"],
    },
    "entity_orbit": {
        "render_kind": "ecosystem_map_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A focused relationship map with one central entity and a small number of legible orbiting actors.",
        "best_for": ["platform ecosystems", "company-product-user relationships", "partnerships"],
        "avoid_when": ["the relationship edges are not stated by the narration or source"],
    },
    "process_trace": {
        "render_kind": "architecture_flow_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A left-to-right system trace with a moving signal that focuses each large step in sequence.",
        "best_for": ["agent workflows", "API pipelines", "model-to-app flows", "deployment chains"],
        "avoid_when": ["the process has fewer than two supported steps"],
    },
    "process_detail_zoom": {
        "render_kind": "process_zoom_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A process overview that zooms into the one step responsible for the narrated consequence.",
        "best_for": ["critical workflow steps", "bottlenecks", "approval or safety gates"],
        "avoid_when": ["there is no clearly supported focus step"],
    },
    "interface_walkthrough": {
        "render_kind": "browser_walkthrough_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A real page or interface capture with a guided cursor/focus journey across two to four targets.",
        "best_for": ["product pages", "documentation", "interface features", "release walkthroughs"],
        "avoid_when": ["no selected source page or focus targets exist"],
    },
    "evidence_stack": {
        "render_kind": "document_stack_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A layered stack of named releases, papers, reports, or issues that resolves onto one focal document.",
        "best_for": ["multiple source artifacts", "release history", "evidence accumulation"],
        "avoid_when": ["the documents or publishers are not present in supplied context"],
    },
    "source_proof_montage": {
        "render_kind": "document_stack_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "Two or three real story-owned source captures layer into view, then the source supporting the active beat takes focus.",
        "best_for": ["multi-source coverage", "corroboration", "showing several primary or reported sources without a static document card"],
        "avoid_when": ["fewer than two available source_page asset IDs exist", "the sources cover unrelated events", "a single focused source capture communicates the beat better"],
    },
    "interface_before_after": {
        "render_kind": "interface_transform_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A before/after workflow transformation with one morphing action path and readable labels.",
        "best_for": ["manual-to-agent workflows", "old versus new product behavior"],
        "avoid_when": ["the before/after states would be invented"],
    },
    "capability_compare": {
        "render_kind": "capability_matrix_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A focused comparison that reveals one capability row at a time and highlights the narrated distinction.",
        "best_for": ["model or product capability comparisons"],
        "avoid_when": ["the comparison cells are not explicitly supported"],
    },
}


def recipe_ids() -> list[str]:
    return list(RECIPE_REGISTRY)


def recipe_specs_for_prompt(
    render_kind: str,
    *,
    allowed_recipe_ids: list[str],
    required_backends: list[str],
) -> list[dict[str, Any]]:
    required = {clean_text(value) for value in required_backends if clean_text(value)}
    allowed = {clean_text(value) for value in allowed_recipe_ids if clean_text(value)}
    output: list[dict[str, Any]] = []
    for recipe_id, raw in RECIPE_REGISTRY.items():
        if recipe_id not in allowed or clean_text(raw.get("render_kind")) != render_kind:
            continue
        supported = {
            clean_text(value) for value in raw.get("supported_backends", []) if clean_text(value)
        }
        if not required.issubset(supported):
            continue
        output.append({"recipe_id": recipe_id, **deepcopy(raw)})
    return output


def validate_scene_recipe(render_kind: str, payload: dict[str, Any]) -> list[str]:
    recipe_id = clean_text(payload.get("recipe_id"))
    if not recipe_id:
        return []
    recipe = RECIPE_REGISTRY.get(recipe_id)
    if not recipe:
        return [f"payload.recipe_id references unknown visual recipe {recipe_id!r}"]
    expected = clean_text(recipe.get("render_kind"))
    if expected != render_kind:
        return [
            f"payload.recipe_id {recipe_id!r} belongs to {expected!r}, not {render_kind!r}"
        ]
    return []
