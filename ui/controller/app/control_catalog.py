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
        "label": "Visuals",
        "description": "Render the episode video from the finished voiceover via the motion-graphics engine (art-director, asset resolver, build, render).",
        "modules": ["visuals"],
        "supports_boundaries": False,
        "provider_risk": "The LLM art director is called unless the deterministic bridge is selected; the asset resolver may fetch logos or stock media.",
    },
}
