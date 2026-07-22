from __future__ import annotations

from ..recipes import ACTIVE_RENDER_KINDS


PACKAGE_TYPE = "visual_scene_plan"
SUPPORTED_FORMAT = "roundup"
EPISODE_DIRECTOR_PROMPT_MODULE = "episode_director"
BOOKEND_VISUAL_PLANNER_PROMPT_MODULE = "bookend_visual_planner"
STORY_VISUAL_PLANNER_PROMPT_MODULE = "story_visual_planner"
STORY_VISUAL_EDITOR_PROMPT_MODULE = "story_visual_editor"
VISUAL_LLM_ROLES = (
    EPISODE_DIRECTOR_PROMPT_MODULE,
    BOOKEND_VISUAL_PLANNER_PROMPT_MODULE,
    STORY_VISUAL_PLANNER_PROMPT_MODULE,
    STORY_VISUAL_EDITOR_PROMPT_MODULE,
)
NEXT_MODULE = "visuals.media_discovery"

RENDER_KINDS = list(ACTIVE_RENDER_KINDS)

# Names from the retired slide/card renderer remain banned provider language,
# but they are not part of any executable scene contract.
OLD_CARD_RENDER_KINDS = {
    "title_card",
    "timeline_card",
    "entity_card",
    "recap_card",
    "fallback_card",
    "quote_card",
    "data_card",
}

DEFAULT_MAX_SCENES = 64
DEFAULT_MIN_SCENE_SECONDS = 3.0
DEFAULT_MAX_SCENE_SECONDS = 14.0
DEFAULT_HARD_MAX_SCENE_SECONDS = 16.0
DEFAULT_MIN_SCENES_PER_STORY = 3
DEFAULT_MAX_SCENES_PER_STORY = 12
DEFAULT_MAX_SOURCE_ARTICLE_SCENES = 20
DEFAULT_MAX_CONTEXT_IMAGE_SCENES = 16
DEFAULT_MAX_BROLL_VIDEO_SCENES = 12
DEFAULT_MAX_LOGO_REVEAL_SCENES = 24
DEFAULT_MAX_EDITORIAL_TEXT_SCENES = 32
DEFAULT_MAX_SIMPLE_EXPLAINER_SCENES = 24
DEFAULT_MAX_STORY_TRANSITION_SCENES = 12
DEFAULT_MAX_QUOTE_OR_CLAIM_SCENES = 18
DEFAULT_MAX_BROWSER_WALKTHROUGH_SCENES = 12
DEFAULT_MAX_DOCUMENT_STACK_SCENES = 12
DEFAULT_MAX_INTERFACE_TRANSFORM_SCENES = 12
DEFAULT_MAX_CONSECUTIVE_SAME_KIND = 2
DEFAULT_MAX_STORY_CONTEXT_CHARS = 500_000


DEFAULT_VISUAL_CAPABILITIES = {
    "source_article_scene": {
        "description": "Use a real selected-story page as visual proof, moving from page context to one exact supplied passage.",
        "best_for": ["headline context", "specific reported details", "visible provenance"],
        "required_payload_fields": [
            "url",
            "source_record_key",
            "target_text",
            "highlight_phrases",
            "crop_strategy",
            "overlay_headline",
            "motion_style",
        ],
        "avoid_when": ["the beat is not source-specific", "no selected source page exists"],
        "render_notes": "Keep the real page dominant. Use a headline push, body-detail focus, or restrained source scan rather than a decorative browser card.",
    },
    "context_image_scene": {
        "description": "Use one verified story-owned image as the dominant shot, optionally with one or two concise annotations.",
        "best_for": ["people", "hardware", "places", "products", "physical context"],
        "required_payload_fields": [
            "asset_id",
            "shot_style",
            "overlay_headline",
            "motion_style",
            "show_overlay",
        ],
        "avoid_when": ["the pixels do not depict the active narration", "a source page is needed as proof"],
        "render_notes": "Prefer full bleed, a strong crop, or one detail move. Text is optional and subordinate to the image.",
    },
    "broll_video_scene": {
        "description": "Use one trusted story-owned video moment to show an action, interface, device, environment, or demo in motion.",
        "best_for": ["demos", "robot motion", "interfaces in use", "labs", "manufacturing"],
        "required_payload_fields": [
            "asset_id",
            "shot_style",
            "overlay_headline",
            "motion_style",
            "show_overlay",
        ],
        "avoid_when": ["no compatible source-video asset exists", "the footage does not show the spoken idea"],
        "render_notes": "Use a selected video moment full bleed or with one timed annotation; narration remains authoritative.",
    },
    "logo_reveal_scene": {
        "description": "Introduce one or two verified identities with a clean editorial lockup, not a logo card.",
        "best_for": ["first entity mention", "partnerships", "lawsuits", "identity resets"],
        "required_payload_fields": [
            "entities",
            "primary_entity",
            "logo_strategy",
            "companion_text",
            "motion_style",
        ],
        "avoid_when": ["the entity is incidental", "real product imagery explains the beat better"],
        "render_notes": "Keep the mark large, preserve clear space, and pair it with one short idea only.",
    },
    "editorial_text_scene": {
        "description": "Use expressive typography for one short hook, punchline, implication, or reset.",
        "best_for": ["hooks", "jokes", "creator reactions", "brief implications"],
        "required_payload_fields": ["headline", "accent_words", "composition", "motion_style"],
        "avoid_when": ["real media can show the subject", "the copy repeats a narration paragraph"],
        "render_notes": "No card, no scene label by default, and no arbitrary narration slice. One complete thought fills the frame.",
    },
    "simple_explainer_scene": {
        "description": "Explain one small mechanism, causal chain, or conceptual contrast using two to four large elements.",
        "best_for": ["small workflows", "cause and effect", "plain-language concept contrasts"],
        "required_payload_fields": ["headline", "items", "orientation", "motion_style"],
        "avoid_when": ["a real image or source communicates the beat better", "more than four elements are needed"],
        "render_notes": "Use transparent SVG/DOM foreground layers, one moving focus, and no panels or dashboard chrome.",
    },
    "story_transition_scene": {
        "description": "Open one roundup story with its complete title, prominent story number, and optional verified media or identity.",
        "best_for": ["the deterministic first beat of each selected story"],
        "required_payload_fields": ["headline", "accent_words", "motion_style"],
        "avoid_when": ["the scene is not a story boundary", "the title is duplicated elsewhere"],
        "render_notes": "Use a clean moving chapter opener, never a silent title slide or small card.",
    },
    "quote_or_claim_highlight_scene": {
        "description": "Keep a real source capture dominant while tracing one concise supported quote, claim, number, or caveat.",
        "best_for": ["direct quotes", "important caveats", "reported numbers", "carefully hedged language"],
        "required_payload_fields": [
            "url",
            "source_record_key",
            "claim_text",
            "supporting_text",
            "target_text",
        ],
        "avoid_when": ["the words cannot be tied to the supplied source", "the beat is a broad transition"],
        "render_notes": "Use an in-context highlight, evidence split, or source-led quote focus. Do not float a dark quote card over the page.",
    },
    "browser_walkthrough_scene": {
        "description": "Guide the viewer through two to four exact targets on a real selected page or interface capture.",
        "best_for": ["product pages", "documentation", "release pages", "interface details"],
        "required_payload_fields": [
            "url",
            "source_record_key",
            "headline",
            "focus_text",
            "walkthrough_steps",
        ],
        "avoid_when": ["no exact targets exist", "one static source detail is sufficient"],
        "render_notes": "Use a guided scroll, cursor trace, or focused zoom on the real capture; avoid simulated dashboard chrome.",
    },
    "document_stack_scene": {
        "description": "Layer real story-owned source captures, papers, filings, or releases and resolve onto one focal document.",
        "best_for": ["multi-source coverage", "evidence accumulation", "one decisive document among related sources"],
        "required_payload_fields": ["headline", "documents", "focus_document_label"],
        "avoid_when": ["only one source exists", "document labels would be invented"],
        "render_notes": "Use real source surfaces and shallow parallax. Avoid fake paper cards when captures are unavailable.",
    },
    "interface_transform_scene": {
        "description": "Show an explicit before-to-after interface or workflow change as one continuous visual transformation.",
        "best_for": ["manual-to-agent workflows", "old versus new behavior", "short process simplification"],
        "required_payload_fields": ["headline", "before", "after", "transformation_label"],
        "avoid_when": ["the before or after state would be invented", "a real interface capture is available"],
        "render_notes": "Use open spatial layers and one morphing path; do not render two dashboard cards side by side.",
    },
}
