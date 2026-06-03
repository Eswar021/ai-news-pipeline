from __future__ import annotations

DROP_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "ref",
    "ref_src",
    "feature",
    "fbclid",
    "gclid",
    "si",
}

DEFAULT_MAX_RESEARCH_PAPERS = 12

RESEARCH_PRIORITY_TERMS = {
    "ai",
    "artificial intelligence",
    "agent",
    "agents",
    "agentic",
    "llm",
    "large language model",
    "language model",
    "coding",
    "code",
    "developer",
    "copilot",
    "rag",
    "reasoning",
    "memory",
    "benchmark",
    "tool",
    "tools",
    "multimodal",
    "vision-language",
    "diffusion",
    "generative ai",
    "deep research",
}

GENERIC_TITLES = {
    "ai",
    "cloud",
    "featured",
    "news",
    "blog",
    "articles",
    "page 2",
    "page 3",
}

LISTING_PATH_PARTS = (
    "/category/",
    "/categories/",
    "/tag/",
    "/tags/",
    "/page/",
    "/topic/",
)

AI_RELEVANCE_TERMS = {
    "ai",
    "artificial intelligence",
    "agent",
    "agents",
    "agentic",
    "chatgpt",
    "claude",
    "codex",
    "copilot",
    "deepmind",
    "gemini",
    "gpt",
    "llm",
    "machine learning",
    "model",
    "multimodal",
    "openai",
    "rag",
    "robotics",
}

CRYPTO_TERMS = {
    "crypto",
    "coin",
    "token",
    "blockchain",
    "protocol price",
    "price prediction",
    "surging",
    "hit new highs",
    "market cap",
}

CRYPTO_DOMAINS = {
    "beincrypto.com",
    "bitcoin.com",
    "coindesk.com",
    "cointelegraph.com",
    "cryptobriefing.com",
    "decrypt.co",
    "theblock.co",
}

CRYPTO_SOURCE_NAMES = {
    "beincrypto",
    "bitcoin.com",
    "coindesk",
    "cointelegraph",
    "crypto briefing",
    "cryptobriefing",
    "decrypt",
    "the block",
}

GENERIC_SOFTWARE_RELEASE_PATTERNS = [
    r"\bissue\s+\d+:\s+.*\breleased\b",
    r"\bdjango\s+\d+(?:\.\d+)*\b.*\breleased\b",
    r"\bgo\s+\d+(?:\.\d+)*\b.*\breleased\b",
    r"\bnode(?:\.js)?\s+\d+(?:\.\d+)*\b.*\breleased\b",
    r"\bruby\s+\d+(?:\.\d+)*\b.*\breleased\b",
    r"\brails\s+\d+(?:\.\d+)*\b.*\breleased\b",
]

GENERAL_DEV_PATTERNS = [
    r"\bwhat'?s new in go\b",
    r"\bcss\b",
    r"\bdjango\b",
    r"\bjavascript\b",
    r"\bpython package\b",
    r"\bweb framework\b",
]

FINANCE_NOISE_PATTERNS = [
    r"\b[A-Z]{1,6}\)\s+(?:soars|jumps|rises|falls|drops|plunges)\b",
    r"\bshares?\s+(?:soar|jump|rise|fall|drop|plunge)\b",
    r"\bstock\s+(?:soars|jumps|rises|falls|drops|plunges)\b",
    r"\bprofits?\s+seen\s+growing\b",
    r"\bprice\s+target\b",
]

PROMO_OR_DEAL_PATTERNS = [
    r"\bapply before\b",
    r"\bapplications close\b",
    r"\bearly bird\b",
    r"\bsave up to\b",
    r"\bpasses?\s+before\b",
    r"\bticket rates?\b",
    r"\bmemorial day sales?\b",
    r"\blast[- ]minute deals?\b",
    r"\banniversary sale\b",
]

LOW_CONTEXT_CONSUMER_PATTERNS = [
    r"\bfavorite .* deals?\b",
    r"\bwebsite imagery\b",
    r"\bsolar power \(on earth\)\b",
]
