from __future__ import annotations

from typing import Any


STAGE_ORDER = ("collect", "content", "voiceover", "visuals")

STAGE_CATALOG: dict[str, dict[str, Any]] = {
    "collect": {
        "label": "Ingestion",
        "description": "Create or reopen a run and collect normalized source records.",
        "modules": ["news_collection"],
        "supports_boundaries": False,
        "provider_risk": "Configured news sources and collection APIs are contacted.",
    },
    "content": {
        "label": "Content",
        "description": "Prepare evidence, make semantic editorial decisions, select stories, write the script, and draft metadata.",
        "modules": [
            "evidence_prep",
            "editorial_triage",
            "story_mapping",
            "editorial_selection",
            "video_packaging",
            "script_generation",
            "metadata_creator",
        ],
        "supports_boundaries": True,
        "provider_risk": "Configured LLM providers can be called.",
    },
    "voiceover": {
        "label": "Voiceover",
        "description": "Synthesize narration and finalize audio-timed metadata.",
        "modules": ["voiceover", "metadata_finalizer"],
        "supports_boundaries": False,
        "provider_risk": "Final synthesis can call a paid speech provider; preview normally uses the local voice route.",
    },
    "visuals": {
        "label": "Visuals and review",
        "description": "Research, plan, resolve, render, assemble, review, and optionally create the publish handoff.",
        "modules": [
            "visual_research",
            "asset_catalog",
            "visual_planner",
            "media_discovery",
            "asset_resolver",
            "visual_render",
            "video_assembly",
            "visual_review",
            "publish_handoff",
        ],
        "supports_boundaries": True,
        "provider_risk": "Generated visual research or planning can call an LLM; enabled discovery providers may also be contacted.",
    },
}
