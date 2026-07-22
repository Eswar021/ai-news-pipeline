from __future__ import annotations

from copy import deepcopy
from typing import Any

from .common import clean_text


ACTIVE_RENDER_KINDS = (
    "source_article_scene",
    "context_image_scene",
    "broll_video_scene",
    "logo_reveal_scene",
    "editorial_text_scene",
    "simple_explainer_scene",
    "story_transition_scene",
    "quote_or_claim_highlight_scene",
    "browser_walkthrough_scene",
    "document_stack_scene",
    "interface_transform_scene",
)


RECIPE_REGISTRY: dict[str, dict[str, Any]] = {
    "editorial_hook": {
        "render_kind": "editorial_text_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A complete hook phrase revealed in two deliberate typographic phases with generous whitespace.",
        "best_for": ["intro hooks", "short punchlines", "one clear implication"],
        "avoid_when": ["real media can show the subject", "more than one idea must be explained"],
    },
    "editorial_punchline": {
        "render_kind": "editorial_text_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A terse payoff lands large, with one accent word and a fast underline snap.",
        "best_for": ["jokes", "ironic payoffs", "short creator reactions"],
        "avoid_when": ["the line needs supporting explanation", "real media can carry the moment"],
    },
    "editorial_reset": {
        "render_kind": "editorial_text_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A quiet visual breath using one complete implication and restrained whitespace.",
        "best_for": ["brief implications", "pace resets", "story takeaways"],
        "avoid_when": ["the narration is still presenting concrete evidence"],
    },
    "chapter_opener": {
        "render_kind": "story_transition_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A clean story chapter reveal, optionally layered over one verified story-owned visual anchor.",
        "best_for": ["the deterministic first beat of a roundup story"],
        "avoid_when": ["the scene is not a story boundary"],
    },
    "chapter_media_opener": {
        "render_kind": "story_transition_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A numbered chapter title enters over one verified full-bleed story image or video.",
        "best_for": ["story openings with a strong physical or product visual"],
        "avoid_when": ["the media does not directly depict the story"],
    },
    "chapter_identity_opener": {
        "render_kind": "story_transition_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A clean chapter reveal pairs the complete story title with one verified identity mark.",
        "best_for": ["company or product stories without strong source imagery"],
        "avoid_when": ["the identity is ambiguous or incidental"],
    },
    "source_proof_scan": {
        "render_kind": "source_article_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A browser-like source proof treatment that moves from headline context to an exact highlighted passage.",
        "best_for": ["source-backed claims", "visible provenance", "article details"],
        "avoid_when": ["the beat is not source-specific", "no exact screenshot target exists"],
    },
    "source_headline_push": {
        "render_kind": "source_article_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "The source page establishes wide, then pushes into its headline and publisher identity.",
        "best_for": ["first source reveal", "headline context", "publisher provenance"],
        "avoid_when": ["a body passage rather than the headline supports the narration"],
    },
    "source_detail_focus": {
        "render_kind": "source_article_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A real page crop moves directly to one supplied body passage with a restrained highlight.",
        "best_for": ["specific details", "method explanations", "reported caveats"],
        "avoid_when": ["the target text is not available in the selected source"],
    },
    "layered_evidence_reveal": {
        "render_kind": "quote_or_claim_highlight_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A source capture with a restrained evidence strip and sequential phrase highlights, not a quote card.",
        "best_for": ["one consequential statement", "a source sentence that needs emphasis"],
        "avoid_when": ["the words are not present in the selected source"],
    },
    "evidence_split": {
        "render_kind": "quote_or_claim_highlight_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A source capture and one concise claim share the frame without a floating quote card.",
        "best_for": ["claim plus provenance", "numbers that need visible source context"],
        "avoid_when": ["the claim cannot remain concise"],
    },
    "quote_source_focus": {
        "render_kind": "quote_or_claim_highlight_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "The source remains dominant while a short attributed phrase is traced in place.",
        "best_for": ["direct quotations", "carefully hedged source wording"],
        "avoid_when": ["the exact words are not present in the source"],
    },
    "annotated_image_focus": {
        "render_kind": "context_image_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A strong crop of verified imagery with one or two timed annotation callouts.",
        "best_for": ["hardware", "people", "places", "product imagery", "physical context"],
        "avoid_when": ["the image descriptor does not establish what the image depicts"],
    },
    "full_bleed_image": {
        "render_kind": "context_image_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "Verified imagery fills the frame with no overlay beyond a small source credit.",
        "best_for": ["strong hero images", "visual breathing room", "physical context"],
        "avoid_when": ["the image needs labels to be understood"],
    },
    "image_detail_sequence": {
        "render_kind": "context_image_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "One verified image moves from establishing crop to a narrated detail with one annotation.",
        "best_for": ["hardware details", "people and products", "source figures"],
        "avoid_when": ["the detail is not visibly present in the image"],
    },
    "annotated_video_focus": {
        "render_kind": "broll_video_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A source-owned video moment with restrained kinetic annotations and editorial reframing.",
        "best_for": ["demos", "robot motion", "interfaces in use", "physical action"],
        "avoid_when": ["the clip does not show the active narration beat"],
    },
    "full_bleed_video": {
        "render_kind": "broll_video_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A selected source-owned video moment plays full frame with only attribution.",
        "best_for": ["demos", "robot motion", "interfaces in use", "physical action"],
        "avoid_when": ["the chosen moment does not show the active narration"],
    },
    "video_detail_sequence": {
        "render_kind": "broll_video_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A source-owned clip reframes toward one action and adds one timed annotation.",
        "best_for": ["product behavior", "manufacturing", "short interface actions"],
        "avoid_when": ["the clip requires several explanatory labels"],
    },
    "identity_reveal": {
        "render_kind": "logo_reveal_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A verified identity mark or clean name treatment enters as part of an editorial composition, not inside a logo card.",
        "best_for": ["first company or product mention", "identity resets", "brand relationships"],
        "avoid_when": ["the identity is ambiguous", "a real product or source image communicates the beat better"],
    },
    "identity_lockup": {
        "render_kind": "logo_reveal_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "One verified mark and one short idea form a restrained editorial lockup.",
        "best_for": ["first entity mention", "short identity resets"],
        "avoid_when": ["the logo would merely decorate an unrelated sentence"],
    },
    "identity_pair_reveal": {
        "render_kind": "logo_reveal_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "Two verified identities enter as a relationship or tension, without a versus card.",
        "best_for": ["partnerships", "lawsuits", "platform relationships"],
        "avoid_when": ["only one identity is relevant or the relationship is unstated"],
    },
    "mechanism_steps": {
        "render_kind": "simple_explainer_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "Two to four large editorial labels assemble into a readable causal or process sequence with one moving focus.",
        "best_for": ["short mechanisms", "cause and effect", "small workflows"],
        "avoid_when": ["more than four steps are required", "the relationship is not stated by the narration"],
    },
    "causal_chain": {
        "render_kind": "simple_explainer_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "Two to four large ideas connect as one cause-and-effect path with a moving focus.",
        "best_for": ["why-this-leads-to-that explanations", "small mechanisms"],
        "avoid_when": ["the causal relationship is not explicit in narration"],
    },
    "concept_contrast": {
        "render_kind": "simple_explainer_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "Two concepts share one clean field and reveal their meaningful difference without a matrix.",
        "best_for": ["ordinary bit versus p-bit", "confidence versus accuracy", "old versus new mental models"],
        "avoid_when": ["the contrast requires unsupported measurements"],
    },
    "interface_walkthrough": {
        "render_kind": "browser_walkthrough_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A real page or interface capture with a guided cursor/focus journey across two to four targets.",
        "best_for": ["product pages", "documentation", "interface features", "release walkthroughs"],
        "avoid_when": ["no selected source page or focus targets exist"],
    },
    "guided_scroll": {
        "render_kind": "browser_walkthrough_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A real page scrolls through two or three supplied targets as the narration advances.",
        "best_for": ["documentation", "release pages", "long source pages"],
        "avoid_when": ["the targets are unavailable or unrelated"],
    },
    "interface_detail_zoom": {
        "render_kind": "browser_walkthrough_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A real interface establishes wide, then zooms to one exact control or result.",
        "best_for": ["product controls", "demo details", "specific documentation sections"],
        "avoid_when": ["the exact interface detail cannot be captured"],
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
    "focal_document": {
        "render_kind": "document_stack_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "Several real documents establish context before one source moves into clear focus.",
        "best_for": ["one decisive paper or filing among related coverage"],
        "avoid_when": ["only one source artifact exists"],
    },
    "interface_before_after": {
        "render_kind": "interface_transform_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A before/after workflow transformation with one morphing action path and readable labels.",
        "best_for": ["manual-to-agent workflows", "old versus new product behavior"],
        "avoid_when": ["the before/after states would be invented"],
    },
    "workflow_morph": {
        "render_kind": "interface_transform_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "A manual workflow collapses into a shorter assisted path through one continuous morph.",
        "best_for": ["manual-to-agent workflows", "multi-step-to-one-action changes"],
        "avoid_when": ["the before and after states are not explicit"],
    },
    "interface_focus_shift": {
        "render_kind": "interface_transform_scene",
        "supported_backends": ["remotion", "hyperframes"],
        "description": "The composition shifts attention from the old interface state to the changed state without panel chrome.",
        "best_for": ["feature changes", "workflow emphasis", "old versus new behavior"],
        "avoid_when": ["the transformation is only speculative"],
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
