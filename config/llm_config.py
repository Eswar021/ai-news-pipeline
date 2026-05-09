"""
LLM model profiles — switch between dev/production/local with one line.

Two levels of control:
  1. ACTIVE_PROFILE — sets the global default for ALL modules
  2. MODULE_OVERRIDES — override specific modules to use a different profile

Example: Run everything on dev (cheap) but use production for the script writer:
  ACTIVE_PROFILE = "dev"
  MODULE_OVERRIDES = {"script_writer": "production"}
"""

LLM_PROFILES = {
    # During development — cheap, fast, good enough for testing pipeline logic
    "dev": {
        "provider": "openai",
        "model": "gpt-5-nano",
        "temperature": 0.15,
    },

    # Production quality — for generating real video scripts
    "production": {
        "provider": "openai",
        "model": "gpt-4o",
        "temperature": 0.3,
    },

    # Gemini — alternative, good free tier
    "gemini": {
        "provider": "gemini",
        "model": "gemini-2.5-flash-lite",
        "temperature": 0.15,
    },

    # Gemini Pro — heavier tasks
    "gemini_pro": {
        "provider": "gemini",
        "model": "gemini-2.5-pro",
        "temperature": 0.2,
    },

    # Local LM Studio — fully offline, no API cost
    "local": {
        "provider": "lmstudio",
        "model": "deepseek-r1-distill-qwen-7b",
        "temperature": 0.15,
    },
}

# ← Change this one line to switch ALL agents globally
ACTIVE_PROFILE = "dev"

# ← Override specific modules to use a different profile.
# Module names match the Layer 3/4 script filenames (without .py).
# If a module is not listed here, it falls back to ACTIVE_PROFILE.
MODULE_OVERRIDES = {
    # "topic_selector": "gemini",
    # "summarizer": "production",
    # "claim_extractor": "production",
    # "context_enricher": "gemini_pro",
    # "script_writer": "production",
}


def get_profile(module_name=None):
    """
    Get the LLM profile for a specific module.
    Falls back to ACTIVE_PROFILE if no override is set.

    Usage:
        profile = get_profile("summarizer")
        llm = make_llm(**profile)
    """
    if module_name and module_name in MODULE_OVERRIDES:
        profile_name = MODULE_OVERRIDES[module_name]
    else:
        profile_name = ACTIVE_PROFILE

    return LLM_PROFILES[profile_name]


def get_active_profile():
    """Return the global active LLM profile dict (no module override)."""
    return LLM_PROFILES[ACTIVE_PROFILE]


if __name__ == "__main__":
    print(f"Active profile: {ACTIVE_PROFILE}")
    print(f"Module overrides: {MODULE_OVERRIDES or '(none)'}")
    print()

    # Show what each module would use
    modules = ["topic_selector", "summarizer", "claim_extractor", "context_enricher", "script_writer"]
    for m in modules:
        p = get_profile(m)
        overridden = m in MODULE_OVERRIDES
        tag = " (overridden)" if overridden else ""
        print(f"  {m:20} → {p['provider']}/{p['model']}{tag}")
