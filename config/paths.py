"""
Centralized path management for the entire project.
Every module imports paths from HERE — no hardcoded paths anywhere else.
"""

from pathlib import Path


# ── Project Root ──
ROOT = Path(__file__).resolve().parent.parent


# ── Config ──
CONFIG_DIR       = ROOT / "config"
SOURCES_YAML     = CONFIG_DIR / "sources.yaml"
QUERIES_YAML     = CONFIG_DIR / "queries.yaml"
CHANNELS_YAML    = CONFIG_DIR / "channels.yaml"
LLM_CONFIG       = CONFIG_DIR / "llm_config.py"
ENV_FILE         = ROOT / ".env"


# ── LLM Utilities ──
LLM_DIR          = ROOT / "llm"


# ── Pipelines ──
PIPELINES_DIR    = ROOT / "pipelines"
LAYER_1_DIR      = PIPELINES_DIR / "layer_1_extraction"
LAYER_2_DIR      = PIPELINES_DIR / "layer_2_processing"
LAYER_3_DIR      = PIPELINES_DIR / "layer_3_intelligence"
LAYER_4_DIR      = PIPELINES_DIR / "layer_4_content"


# ── Prompts ──
PROMPTS_DIR      = ROOT / "prompts"
PROMPTS_V1       = PROMPTS_DIR / "v1"


# ── Output (layer-wise) ──
OUTPUT_DIR       = ROOT / "output"
LLM_LOGS         = OUTPUT_DIR / "llm_logs"

# Layer 1 — Raw collected data
RAW_OUTPUT       = OUTPUT_DIR / "layer_1_raw"
RAW_ARXIV        = RAW_OUTPUT / "arxiv"
RAW_HACKERNEWS   = RAW_OUTPUT / "hackernews"
RAW_NEWSAPI      = RAW_OUTPUT / "newsapi"
RAW_NEWSDATA     = RAW_OUTPUT / "newsdata"
RAW_MEDIASTACK   = RAW_OUTPUT / "mediastack"
RAW_BLOGS        = RAW_OUTPUT / "blogs"
RAW_REDDIT       = RAW_OUTPUT / "reddit"
RAW_GITHUB       = RAW_OUTPUT / "github"
RAW_YOUTUBE      = RAW_OUTPUT / "youtube"

# Layer 2 — Processed/normalized data
PROCESSED_OUTPUT = OUTPUT_DIR / "layer_2_processed"
PROCESSED_DOCS   = PROCESSED_OUTPUT / "documents"
PROCESSED_CLUSTERS = PROCESSED_OUTPUT / "clusters"
PROCESSED_RANKINGS = PROCESSED_OUTPUT / "rankings"

# Layer 3 — Intelligence outputs
INTEL_OUTPUT     = OUTPUT_DIR / "layer_3_intelligence"
INTEL_SUMMARIES  = INTEL_OUTPUT / "summaries"
INTEL_RESEARCH   = INTEL_OUTPUT / "research"
INTEL_CONTEXT    = INTEL_OUTPUT / "context_packets"

# Layer 4 — Final content
CONTENT_OUTPUT   = OUTPUT_DIR / "layer_4_content"
CONTENT_SCRIPTS  = CONTENT_OUTPUT / "scripts"


# ── Docs ──
DOCS_DIR         = ROOT / "docs"


def ensure_output_dirs():
    """Create all output directories if they don't exist."""
    dirs = [
        RAW_ARXIV, RAW_HACKERNEWS, RAW_NEWSAPI, RAW_NEWSDATA,
        RAW_MEDIASTACK, RAW_BLOGS, RAW_REDDIT, RAW_GITHUB, RAW_YOUTUBE,
        PROCESSED_DOCS, PROCESSED_CLUSTERS, PROCESSED_RANKINGS,
        INTEL_SUMMARIES, INTEL_RESEARCH, INTEL_CONTEXT,
        CONTENT_SCRIPTS,
        LLM_LOGS,
        PROMPTS_V1,
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    ensure_output_dirs()
    print(f"Project root: {ROOT}")
    print(f"Output dir:   {OUTPUT_DIR}")
    print("All output directories created.")
