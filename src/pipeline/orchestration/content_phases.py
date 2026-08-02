"""The Phase-1 / Phase-2 boundary, named once.

Phase-1 is the shared corpus — collection through editorial selection — that is
format-agnostic and can feed many productions. Phase-2 begins at video_packaging
and is per-format. A derived run reuses Phase-1 from an existing run and re-runs
Phase-2 with a different profile/format, so both the content stage and the derive
primitive read the boundary from here rather than hardcoding module lists.
"""
from __future__ import annotations

# Shared corpus, in pipeline order. news_collection is produced by the ingestion
# stage; the rest by the content stage's Phase-1 modules.
SHARED_CORPUS_MODULES: tuple[str, ...] = (
    "news_collection",
    "evidence_prep",
    "editorial_triage",
    "story_mapping",
    "editorial_selection",
)

# The stage that owns each shared-corpus module's config (for config resolution).
SHARED_CORPUS_MODULE_STAGE: dict[str, str] = {
    "news_collection": "ingestion",
    "evidence_prep": "content",
    "editorial_triage": "content",
    "story_mapping": "content",
    "editorial_selection": "content",
}

# The handoff artifact a run must have completed before it can be derived from.
SHARED_CORPUS_TERMINAL_MODULE = "editorial_selection"

# Phase-2 (per-format production) begins here; a derive re-runs from this module.
PHASE2_ENTRY_MODULE = "video_packaging"
