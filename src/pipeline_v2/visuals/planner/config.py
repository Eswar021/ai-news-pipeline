from __future__ import annotations


PACKAGE_TYPE = "visual_scene_plan"
SUPPORTED_FORMAT = "roundup"
EPISODE_DIRECTOR_PROMPT_MODULE = "episode_director"
STORY_VISUAL_PLANNER_PROMPT_MODULE = "story_visual_planner"
NEXT_MODULE = "visuals.asset_resolver"

RENDER_KINDS = [
    "source_article_scene",
    "logo_reveal_scene",
    "kinetic_type_scene",
]

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
DEFAULT_MIN_SCENES_PER_STORY = 3
DEFAULT_MAX_SCENES_PER_STORY = 8
DEFAULT_MAX_SOURCE_ARTICLE_SCENES = 20
DEFAULT_MAX_LOGO_REVEAL_SCENES = 24
DEFAULT_MAX_KINETIC_TYPE_SCENES = 32
DEFAULT_MAX_RECORDS_PER_STORY = 4
DEFAULT_MAX_RECORD_CHARS = 2200

DEFAULT_VISUAL_CAPABILITIES = {
    "source_article_scene": {
        "description": "Show a real source webpage, article, blog, paper, or report as visual proof for a narration beat.",
        "best_for": [
            "source-backed details",
            "headline reveals",
            "important claims that benefit from visible provenance",
            "showing article context while the narrator explains the story",
        ],
        "required_payload_fields": [
            "url",
            "source_record_key",
            "target_text",
            "highlight_phrases",
            "crop_strategy",
            "overlay_headline",
            "motion_style",
        ],
        "avoid_when": [
            "no selected source URL exists",
            "the narration is a broad transition rather than a source-specific point",
            "the scene would become a static slide with too much text",
        ],
        "render_notes": "Use article zooms, headline/body focus, and highlight scans. Never invent URLs or quotes.",
    },
    "logo_reveal_scene": {
        "description": "Use company, product, model, or platform logos/entities as a quick YouTube-style identity moment.",
        "best_for": [
            "introducing a company or product",
            "contrasting two entities",
            "moving between stories",
            "creating quick recognition without a full screenshot",
        ],
        "required_payload_fields": [
            "entities",
            "primary_entity",
            "logo_strategy",
            "companion_text",
            "motion_style",
        ],
        "avoid_when": [
            "the story is about a source claim that needs article grounding",
            "the entity is unclear",
            "the companion text would duplicate a full sentence from narration",
        ],
        "render_notes": "Prefer short companion text, logo stacks, spotlights, and pop/slide reveals.",
    },
    "kinetic_type_scene": {
        "description": "Animate short phrases from the narration with typewriter, word snap, highlight sweep, or similar motion.",
        "best_for": [
            "retention beats",
            "transitions",
            "key takeaways",
            "moments where no source screenshot or logo is the right visual",
        ],
        "required_payload_fields": [
            "phrases",
            "emphasis_words",
            "animation_style",
            "background_motif",
        ],
        "avoid_when": [
            "the phrase is too long for on-screen reading",
            "the scene would become a wall of text",
            "a source article is needed for credibility at that moment",
        ],
        "render_notes": "Keep phrases short and punchy. Use motion, emphasis, and atmosphere rather than cards.",
    },
}
