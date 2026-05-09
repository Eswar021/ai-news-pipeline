# AI News Pipeline 🤖📰

> An end-to-end AI pipeline that collects news & research from multiple sources, processes and clusters them, runs LLM-powered intelligence analysis, and auto-generates YouTube video scripts.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
  - [Environment Variables](#environment-variables)
  - [LLM Profiles](#llm-profiles)
  - [News Sources](#news-sources)
- [Running the Pipeline](#running-the-pipeline)
  - [Run All Layers (Full Pipeline)](#run-all-layers-full-pipeline)
  - [Run Individual Layers](#run-individual-layers)
- [Output](#output)
- [Design Docs](#design-docs)

---

## Overview

The **AI News Pipeline** is a fully modular, 4-layer content automation system. It ingests raw news and research data from a wide range of sources — news APIs, arXiv, Hacker News, GitHub, YouTube — and passes it through progressively deeper AI processing stages to produce polished, ready-to-use YouTube video scripts.

**End-to-end flow:**

```
[Sources] → Layer 1: Extract → Layer 2: Process → Layer 3: Intelligence → Layer 4: Content
```

---

## Architecture

| Layer | Module | Role |
|-------|--------|------|
| **Layer 1** | `pipelines/layer_1_extraction/` | Collect raw data from all sources |
| **Layer 2** | `pipelines/layer_2_processing/` | Normalize, deduplicate, cluster & rank |
| **Layer 3** | `pipelines/layer_3_intelligence/` | AI summarization, claim extraction, context enrichment |
| **Layer 4** | `pipelines/layer_4_content/` | Script planning, writing & output packaging |

```
┌─────────────────────────────────────────────────────────────────┐
│                        AI News Pipeline                          │
│                                                                   │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌──────┐│
│  │  Layer 1    │ → │  Layer 2    │ → │  Layer 3    │ → │  L4  ││
│  │ Extraction  │   │ Processing  │   │Intelligence │   │Script││
│  └─────────────┘   └─────────────┘   └─────────────┘   └──────┘│
│                                                                   │
│  Sources: NewsAPI · NewsData · MediaStack · ArXiv               │
│           Hacker News · GitHub · YouTube · Company Blogs        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
ai-news-pipeline/
│
├── .env.example                  # Template for secrets (copy to .env)
├── requirements.txt              # Python dependencies
│
├── config/
│   ├── llm_config.py             # LLM profiles & active profile switcher
│   ├── paths.py                  # Centralized path management
│   ├── sources.yaml              # News source configurations
│   └── channels.yaml            # YouTube channel configurations
│
├── llm/
│   ├── llm_client.py             # Unified LLM client (OpenAI / Gemini / LM Studio)
│   └── llm_logger.py             # Structured JSON logging for all LLM calls
│
├── prompts/
│   └── v1/                       # Versioned prompt templates
│
├── pipelines/
│   ├── layer_1_extraction/       # Data collection agents
│   │   ├── run_extraction.py     ← Entry point for Layer 1
│   │   ├── arxiv_collector.py
│   │   ├── hackernews_collector.py
│   │   ├── newsapi_collector.py
│   │   ├── newsdata_collector.py
│   │   ├── mediastack_collector.py
│   │   ├── github_collector.py
│   │   └── youtube_collector.py
│   │
│   ├── layer_2_processing/       # Normalization & ranking
│   │   ├── run_processing.py     ← Entry point for Layer 2
│   │   ├── normalizer.py
│   │   ├── deduplicator.py
│   │   ├── clusterer.py
│   │   └── ranker.py
│   │
│   ├── layer_3_intelligence/     # LLM-powered analysis
│   │   ├── run_intelligence.py   ← Entry point for Layer 3
│   │   ├── topic_selector.py
│   │   ├── summarizer.py
│   │   ├── claim_extractor.py
│   │   ├── context_builder.py
│   │   └── context_enricher.py
│   │
│   └── layer_4_content/          # Script generation
│       ├── run_content.py        ← Entry point for Layer 4
│       ├── script_planner.py
│       ├── script_writer.py
│       └── output_packager.py
│
├── output/                       # Runtime outputs (git-ignored)
│   ├── layer_1_raw/
│   ├── layer_2_processed/
│   ├── layer_3_intelligence/
│   ├── layer_4_content/
│   └── llm_logs/
│
└── docs/
    └── system_design_docs/       # Layer-wise technical design documents
        ├── master_system_design.md
        ├── layer_1.md
        ├── layer_2.md
        ├── layer_3.md
        └── layer_4.md
```

---

## Prerequisites

- **Python 3.10+**
- At least one active API key from the list below
- (Optional) [LM Studio](https://lmstudio.ai/) for fully local/offline LLM usage

---

## Installation

**1. Clone the repository**

```bash
git clone https://github.com/YOUR_USERNAME/ai-news-pipeline.git
cd ai-news-pipeline
```

**2. Create and activate a virtual environment**

```bash
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

**3. Install dependencies**

```bash
pip install -r requirements.txt
```

**4. Set up environment variables**

```bash
cp .env.example .env
```

Open `.env` and fill in your API keys (see [Configuration](#configuration) below).

**5. Create output directories**

```bash
python config/paths.py
```

---

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and fill in the keys for the sources you want to use.  
You only need keys for the sources you plan to activate.

```ini
# ── News APIs ─────────────────────────────────────────────────────
NEWSDATA_API=your_newsdata_api_key
MEDIASTACK_API=your_mediastack_api_key
NewsAPI=your_newsapi_key

# ── YouTube Data API ──────────────────────────────────────────────
YOUTUBE_API_KEY=your_youtube_api_key

# ── LLM: Google Gemini ────────────────────────────────────────────
GOOGLE_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash-lite

# ── LLM: OpenAI ───────────────────────────────────────────────────
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4o

# ── LLM: Local (LM Studio) ────────────────────────────────────────
LMSTUDIO_BASE_URL=http://localhost:1234/v1
LMSTUDIO_MODEL=your_local_model_name
LMSTUDIO_API_KEY=lm-studio
```

> **Never commit your real `.env` file.** It is listed in `.gitignore`.

---

### LLM Profiles

LLM behaviour is controlled centrally in `config/llm_config.py`.

**Switch all agents globally** by changing one line:

```python
# config/llm_config.py
ACTIVE_PROFILE = "dev"        # cheap & fast — for testing
# ACTIVE_PROFILE = "production" # GPT-4o quality
# ACTIVE_PROFILE = "gemini"    # Gemini Flash — good free tier
# ACTIVE_PROFILE = "local"     # Fully offline via LM Studio
```

**Override specific modules** without changing the global default:

```python
MODULE_OVERRIDES = {
    "script_writer": "production",   # use GPT-4o only for final script
    "summarizer": "gemini",          # use Gemini for summaries
}
```

Available profiles:

| Profile | Provider | Model | Use Case |
|---------|----------|-------|----------|
| `dev` | OpenAI | gpt-5-nano | Development & testing |
| `production` | OpenAI | gpt-4o | Final content generation |
| `gemini` | Google | gemini-2.5-flash-lite | Free-tier alternative |
| `gemini_pro` | Google | gemini-2.5-pro | Heavy reasoning tasks |
| `local` | LM Studio | *(your local model)* | Fully offline, zero cost |

---

### News Sources

Active sources are configured in `config/sources.yaml`.  
YouTube channels are configured in `config/channels.yaml`.

---

## Running the Pipeline

### Run All Layers (Full Pipeline)

Run each layer in sequence:

```bash
# Layer 1 — Collect raw data from all sources
python pipelines/layer_1_extraction/run_extraction.py

# Layer 2 — Normalize, deduplicate, cluster & rank
python pipelines/layer_2_processing/run_processing.py

# Layer 3 — AI intelligence analysis
python pipelines/layer_3_intelligence/run_intelligence.py

# Layer 4 — Generate final video scripts
python pipelines/layer_4_content/run_content.py
```

### Run Individual Layers

Each layer can be run independently as long as the previous layer's output exists:

```bash
# Example: re-run only the content generation step
python pipelines/layer_4_content/run_content.py
```

---

## Output

All generated files land in the `output/` directory (git-ignored):

| Path | Contents |
|------|----------|
| `output/layer_1_raw/` | Raw JSON from each source (arxiv, newsapi, etc.) |
| `output/layer_2_processed/` | Normalized documents, clusters, rankings |
| `output/layer_3_intelligence/` | Summaries, claim extracts, context packets |
| `output/layer_4_content/scripts/` | **Final video scripts** (JSON + Markdown) |
| `output/llm_logs/` | Structured JSON logs of every LLM call |

---

## Design Docs

Detailed technical design documents for each layer are in `docs/system_design_docs/`:

| Document | Description |
|----------|-------------|
| [master_system_design.md](docs/system_design_docs/master_system_design.md) | Full system overview & data flow |
| [layer_1.md](docs/system_design_docs/layer_1.md) | Extraction layer design |
| [layer_2.md](docs/system_design_docs/layer_2.md) | Processing layer design |
| [layer_3.md](docs/system_design_docs/layer_3.md) | Intelligence layer design |
| [layer_4.md](docs/system_design_docs/layer_4.md) | Content generation layer design |

---

## License

MIT
