"""
Centralized path management for the entire project.
Every module imports paths from HERE — no hardcoded paths anywhere else.
"""

from pathlib import Path


# ── Project Root ──
ROOT = Path(__file__).resolve().parent.parent


# ── Config ──
CONFIG_DIR             = ROOT / "config"
REGISTRIES_DIR         = CONFIG_DIR / "registries"
POLICIES_DIR           = CONFIG_DIR / "policies"

SOURCES_YAML           = REGISTRIES_DIR / "sources.yaml"
CHANNELS_YAML          = REGISTRIES_DIR / "channels.yaml"
CHANNEL_THESIS_YAML    = REGISTRIES_DIR / "channel_thesis.yaml"
AUDIENCE_PROFILES_YAML = REGISTRIES_DIR / "audience_profiles.yaml"
ENTITY_TOPIC_TAXONOMY_YAML = REGISTRIES_DIR / "entity_topic_taxonomy.yaml"

PIPELINE_CONFIG_YAML   = POLICIES_DIR / "pipeline_config.yaml"
FORMAT_CONFIG_YAML     = POLICIES_DIR / "format_config.yaml"
SCORING_CONFIG_YAML    = POLICIES_DIR / "scoring_config.yaml"
QUALITY_RULES_YAML     = POLICIES_DIR / "quality_rules.yaml"
RUN_DEFAULTS_YAML      = POLICIES_DIR / "run_defaults.yaml"
RUN_PROFILES_YAML      = POLICIES_DIR / "run_profiles.yaml"
SOURCE_STRATEGY_YAML   = POLICIES_DIR / "source_strategy.yaml"
CHATGPT_PROMPTS_YAML   = POLICIES_DIR / "chatgpt_prompts.yaml"
ENV_FILE               = ROOT / ".env"
SECRETS_DIR            = ROOT / "secrets"


# ── LLM Utilities ──
LLM_DIR                = ROOT / "llm"


# ── Pipelines ──
PIPELINES_DIR          = ROOT / "pipelines"
LAYER_0_DIR            = PIPELINES_DIR / "layer_0_control"
LAYER_1_DIR            = PIPELINES_DIR / "layer_1_extraction"
LAYER_2_DIR            = PIPELINES_DIR / "layer_2_canonicalization"
LAYER_3_DIR            = PIPELINES_DIR / "layer_3_story_processing"
LAYER_4_DIR            = PIPELINES_DIR / "layer_4_evidence_intelligence"
LAYER_5_DIR            = PIPELINES_DIR / "layer_5_editorial_intelligence"
LAYER_6_DIR            = PIPELINES_DIR / "layer_6_research_packets"
LAYER_7_DIR            = PIPELINES_DIR / "layer_7_content_planning"
LAYER_8_DIR            = PIPELINES_DIR / "layer_8_script_generation"
LAYER_9_DIR            = PIPELINES_DIR / "layer_9_verification_firewall"
LAYER_10_DIR           = PIPELINES_DIR / "layer_10_memory_learning"


# ── Schemas ──
SCHEMAS_DIR            = ROOT / "schemas"


# ── Data — intermediate pipeline outputs (per-run, not final) ──
DATA_DIR               = ROOT / "data"

# Layer 0 — Run manifests
RUNS_DIR               = DATA_DIR / "runs"

# Layer 1 — Raw extracted documents
RAW_DIR                = DATA_DIR / "raw"
RAW_PAYLOADS_DIR       = RAW_DIR / "payloads"

# Layer 2 — Canonical documents + evidence store
CANONICAL_DIR          = DATA_DIR / "canonical"
CANONICAL_CLEAN_TEXT   = CANONICAL_DIR / "clean_text"

# Layer 3 — Story clusters + rankings
STORIES_DIR            = DATA_DIR / "stories"

# Layer 4 — Atomic claims + evidence intelligence
EVIDENCE_DIR           = DATA_DIR / "evidence"

# Layer 5 — Editorial decisions + selected brief
EDITORIAL_DIR          = DATA_DIR / "editorial"

# Layer 6 — Format-specific research packets
PACKETS_DIR            = DATA_DIR / "packets"

# Layer 7 — Video plans + script writer briefs
CONTENT_PLANS_DIR      = DATA_DIR / "content_plans"


# ── Memory — persistent cross-run knowledge ──
MEMORY_DIR             = ROOT / "memory"
VIDEO_MEMORY           = MEMORY_DIR / "video_memory.jsonl"
STORY_COVERAGE_MEMORY  = MEMORY_DIR / "story_coverage_memory.jsonl"
CLAIM_LEDGER           = MEMORY_DIR / "claim_ledger.jsonl"
ENTITY_TOPIC_MEMORY    = MEMORY_DIR / "entity_topic_memory.jsonl"
SOURCE_MEMORY          = MEMORY_DIR / "source_memory.jsonl"
EDITORIAL_PATTERN_MEM  = MEMORY_DIR / "editorial_pattern_memory.jsonl"
FOLLOWUPS              = MEMORY_DIR / "followups.jsonl"
EVIDENCE_GAP_WATCHLIST = MEMORY_DIR / "evidence_gap_watchlist.jsonl"
REJECTED_CLAIM_PATTERNS= MEMORY_DIR / "rejected_claim_patterns.jsonl"
PERFORMANCE_MEMORY     = MEMORY_DIR / "performance_memory.jsonl"
LEARNING_SIGNALS       = MEMORY_DIR / "learning_signals.jsonl"
MEMORY_INDEX           = MEMORY_DIR / "memory_index.json"
MEMORY_SNAPSHOT        = MEMORY_DIR / "memory_snapshot.json"
PUBLISHING_CHANNEL_STATE = MEMORY_DIR / "publishing_channel_state.json"
PUBLISHED_VIDEO_INVENTORY = MEMORY_DIR / "published_video_inventory.jsonl"


# ── Output — final publishable scripts only ──
OUTPUT_DIR             = ROOT / "output"
SCRIPTS_OUTPUT         = OUTPUT_DIR / "scripts"
APPROVAL_REPORTS       = OUTPUT_DIR / "approval_reports"
LLM_LOGS               = OUTPUT_DIR / "llm_logs"


# ── Docs ──
DOCS_DIR               = ROOT / "docs"
DESIGN_DOCS_DIR        = DOCS_DIR / "system_design_docs"


# ─────────────────────────────────────────────────────────
# Legacy paths — kept for backward compatibility.
# Old standalone collectors (arxiv_collector.py etc.) write
# here when run directly. The new run-scoped pipeline writes
# to data/runs/{run_id}/layer_1/ instead.
# ─────────────────────────────────────────────────────────
_LEGACY_RAW_OUTPUT       = OUTPUT_DIR / "layer_1_raw"
_LEGACY_PROCESSED_OUTPUT = OUTPUT_DIR / "layer_2_processed"
_LEGACY_INTEL_OUTPUT     = OUTPUT_DIR / "layer_3_intelligence"
_LEGACY_CONTENT_OUTPUT   = OUTPUT_DIR / "layer_4_content"

# Per-source legacy output dirs (used by standalone collector __main__ blocks)
RAW_ARXIV       = _LEGACY_RAW_OUTPUT / "arxiv"
RAW_HACKERNEWS  = _LEGACY_RAW_OUTPUT / "hackernews"
RAW_NEWSAPI     = _LEGACY_RAW_OUTPUT / "newsapi"
RAW_NEWSDATA    = _LEGACY_RAW_OUTPUT / "newsdata"
RAW_MEDIASTACK  = _LEGACY_RAW_OUTPUT / "mediastack"
RAW_GITHUB      = _LEGACY_RAW_OUTPUT / "github"
RAW_YOUTUBE     = _LEGACY_RAW_OUTPUT / "youtube"
RAW_BLOGS       = _LEGACY_RAW_OUTPUT / "blogs"
RAW_OUTPUT      = _LEGACY_RAW_OUTPUT


def ensure_all_dirs():
    """Create all pipeline directories if they don't exist."""
    dirs = [
        # Data pipeline dirs
        RUNS_DIR,
        REGISTRIES_DIR,
        POLICIES_DIR,
        RAW_DIR, RAW_PAYLOADS_DIR,
        CANONICAL_DIR, CANONICAL_CLEAN_TEXT,
        STORIES_DIR,
        EVIDENCE_DIR,
        EDITORIAL_DIR,
        PACKETS_DIR,
        CONTENT_PLANS_DIR,
        # Memory
        MEMORY_DIR,
        # Output
        SCRIPTS_OUTPUT,
        APPROVAL_REPORTS,
        LLM_LOGS,
        # Secrets
        SECRETS_DIR,
        # Schemas
        SCHEMAS_DIR,
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def ensure_output_dirs():
    """Alias for backward compatibility. Prefer ensure_all_dirs()."""
    ensure_all_dirs()


if __name__ == "__main__":
    ensure_all_dirs()
    print(f"Project root: {ROOT}")
    print(f"Data dir:     {DATA_DIR}")
    print(f"Output dir:   {OUTPUT_DIR}")
    print(f"Memory dir:   {MEMORY_DIR}")
    print("All directories ensured.")
