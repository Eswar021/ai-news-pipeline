from __future__ import annotations

import re
from urllib.parse import urlparse

from src.pipeline.L1_collection.common import clean_text


ORG_ALIAS_MAP: dict[str, tuple[str, ...]] = {
    "openai": ("openai", "chatgpt", "codex"),
    "anthropic": ("anthropic", "claude", "claude code"),
    "google": ("google", "google deepmind", "deepmind", "google cloud", "vertex ai", "gemini"),
    "meta": ("meta", "meta ai", "llama"),
    "microsoft": ("microsoft", "azure ai", "copilot", "phi"),
    "amazon": ("amazon", "aws", "amazon nova", "nova"),
    "huggingface": ("hugging face", "huggingface", "granite"),
    "nvidia": ("nvidia", "cuda", "dgx"),
    "docker": ("docker", "docker agent"),
    "databricks": ("databricks",),
    "apple": ("apple", "siri"),
    "sony": ("sony",),
}

PRODUCT_ALIAS_MAP: dict[str, tuple[str, ...]] = {
    "chatgpt": ("chatgpt", "gpt-5.5", "gpt 5.5", "gpt-5", "gpt 5"),
    "codex": ("codex",),
    "claude": ("claude", "claude code", "claude opus"),
    "gemini": ("gemini",),
    "llama": ("llama",),
    "copilot": ("copilot",),
    "nova": ("nova",),
    "vertex_ai": ("vertex ai",),
    "docker_agent": ("docker agent",),
    "openclaw": ("openclaw",),
}

TUTORIAL_PATTERNS = [
    r"\bhow to\b",
    r"\bhow .* use\b",
    r"\bhow [a-z0-9\s\-]+ use\b",
    r"\bguide\b",
    r"\btutorial\b",
    r"\bwalkthrough\b",
    r"\bdemo\b",
    r"\buse cases?\b",
    r"\bbuild(?:ing)?\b",
]
UPDATE_PATTERNS = [
    r"\bintroducing\b",
    r"\bannounce(?:s|d)?\b",
    r"\blaunch(?:es|ed)?\b",
    r"\bbrings?\b",
    r"\bbring\b",
    r"\bnow available\b",
    r"\brolling out\b",
    r"\bpartner(?:s|ed)?\b",
    r"\bteam up\b",
    r"\braises?\b",
    r"\bban(?:s|ned)?\b",
    r"\bretir(?:e|es|ing)\b",
]
REACTION_PATTERNS = [
    r"\btrust\b",
    r"\bboo(?:ed|ing)?\b",
    r"\bconcern(?:s)?\b",
    r"\bretiring\b",
    r"\breportedly\b",
    r"\bcriticism\b",
    r"\bbacklash\b",
]
INFRA_PATTERNS = [
    r"\bgpu\b",
    r"\bchip\b",
    r"\bdata center\b",
    r"\bcompute\b",
    r"\bkernel exploit\b",
]

ACTION_PATTERNS: dict[str, tuple[str, ...]] = {
    "launch": (r"\bintroducing\b", r"\bannounce(?:s|d)?\b", r"\blaunch(?:es|ed)?\b", r"\bnow available\b", r"\brolling out\b", r"\bbrings?\b", r"\bbring\b"),
    "partner": (r"\bpartner(?:s|ed)?\b", r"\bteam up\b", r"\bcollaborat(?:e|es|ed|ion)\b"),
    "raise": (r"\braises?\b", r"\bseries [abc]\b", r"\bfunding\b"),
    "retire": (r"\bretir(?:e|es|ing)\b", r"\bshutdown\b", r"\bdeprecat(?:e|es|ed)\b", r"\bban(?:s|ned)?\b"),
    "security": (r"\bsecurity\b", r"\bexploit\b", r"\bbug reports?\b", r"\bmalware\b", r"\bkernel\b"),
    "trust": (r"\btrust\b", r"\bboo(?:ed|ing)?\b", r"\bcriticism\b", r"\bbacklash\b"),
    "benchmark": (r"\bleaderboard\b", r"\bbenchmark\b", r"\bevaluat(?:e|ion|ors)\b"),
    "memory": (r"\bmemory\b", r"\bpatterns\b"),
    "voice": (r"\bvoice\b", r"\bsonic\b"),
    "tooling": (r"\bshow hn\b", r"\bopen[- ]source\b", r"\brepository\b", r"\brepo\b"),
}

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "for",
    "from",
    "how",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "their",
    "this",
    "to",
    "use",
    "uses",
    "using",
    "with",
    "your",
    "teams",
    "team",
}

GENERIC_STORY_TOKENS = {
    "agent",
    "agents",
    "ai",
    "app",
    "apps",
    "assistant",
    "assistants",
    "code",
    "custom",
    "data",
    "enterprise",
    "future",
    "intelligence",
    "learning",
    "model",
    "models",
    "platform",
    "product",
    "products",
    "real-time",
    "system",
    "systems",
    "tool",
    "tools",
    "workflow",
    "workflows",
}


def extract_record_signals(record: dict) -> dict:
    source_label = canonical_source_label(record)
    compact_text = _compact_search_text(record)
    search_text = _search_text(record)
    title_tokens = _title_tokens(record.get("title", ""))
    org_hints = _extract_aliases(search_text, ORG_ALIAS_MAP)
    product_hints = _extract_aliases(search_text, PRODUCT_ALIAS_MAP)
    action_hints = _extract_action_hints(compact_text)

    repo_name = _repo_name(record.get("url", ""))
    if repo_name:
        product_hints.add(repo_name)

    event_type_hint = _classify_event_type(record, compact_text)
    story_key_tokens = _story_key_tokens(title_tokens, org_hints, product_hints, action_hints)
    return {
        "source_label": source_label,
        "org_hints": org_hints,
        "product_hints": product_hints,
        "action_hints": action_hints,
        "event_type_hint": event_type_hint,
        "title_tokens": title_tokens,
        "title_overlap_tokens": title_tokens - STOPWORDS,
        "story_key_tokens": story_key_tokens,
        "anchor_story_tokens": {token for token in story_key_tokens if len(token) >= 8},
    }


def canonical_source_label(record: dict) -> str:
    return clean_text(
        record.get("provider")
        or record.get("source_name")
        or record.get("channel_name")
        or record.get("source")
        or "unknown"
    )


def title_overlap_stats(left: dict, right: dict) -> tuple[int, float]:
    left_tokens = left["_title_overlap_tokens"]
    right_tokens = right["_title_overlap_tokens"]
    if not left_tokens and not right_tokens:
        return 0, 0.0
    overlap = left_tokens & right_tokens
    union = left_tokens | right_tokens
    jaccard = len(overlap) / len(union) if union else 0.0
    return len(overlap), jaccard


def story_key_overlap_stats(left: dict, right: dict) -> tuple[int, float, int]:
    left_tokens = left["_story_key_tokens"]
    right_tokens = right["_story_key_tokens"]
    if not left_tokens and not right_tokens:
        return 0, 0.0, 0
    overlap = left_tokens & right_tokens
    union = left_tokens | right_tokens
    anchor_overlap = len(left["_anchor_story_tokens"] & right["_anchor_story_tokens"])
    jaccard = len(overlap) / len(union) if union else 0.0
    return len(overlap), jaccard, anchor_overlap


def _compact_search_text(record: dict) -> str:
    parts = [
        record.get("title", ""),
        record.get("description", ""),
        record.get("summary", ""),
        record.get("source_name", ""),
        record.get("channel_name", ""),
    ]
    return clean_text(" ".join(part for part in parts if part)).lower()


def _search_text(record: dict) -> str:
    parts = [
        record.get("title", ""),
        record.get("description", ""),
        record.get("summary", ""),
        record.get("source_name", ""),
        record.get("channel_name", ""),
        clean_text(record.get("content", ""))[:1400],
    ]
    return clean_text(" ".join(part for part in parts if part)).lower()


def _title_tokens(title: str) -> set[str]:
    tokens: set[str] = set()
    for token in re.findall(r"[a-z0-9\+\-\.]+", clean_text(title).lower()):
        if len(token) < 3 and token != "ai":
            continue
        tokens.add(token)
    return tokens


def _extract_aliases(text: str, alias_map: dict[str, tuple[str, ...]]) -> set[str]:
    found: set[str] = set()
    for canonical, aliases in alias_map.items():
        for alias in aliases:
            pattern = r"\b" + re.escape(alias.lower()).replace(r"\ ", r"\s+") + r"\b"
            if re.search(pattern, text):
                found.add(canonical)
                break
    return found


def _extract_action_hints(text: str) -> set[str]:
    actions: set[str] = set()
    for action, patterns in ACTION_PATTERNS.items():
        if _matches_any(text, list(patterns)):
            actions.add(action)
    return actions


def _story_key_tokens(
    title_tokens: set[str],
    org_hints: set[str],
    product_hints: set[str],
    action_hints: set[str],
) -> set[str]:
    tokens = {token for token in title_tokens if token not in STOPWORDS and token not in GENERIC_STORY_TOKENS}
    tokens.update(org_hints)
    tokens.update(product_hints)
    tokens.update(action_hints)
    return tokens


def _repo_name(url: str) -> str:
    raw = clean_text(url)
    if not raw:
        return ""
    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host != "github.com":
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return ""
    return clean_text(parts[1]).lower()


def _classify_event_type(record: dict, compact_text: str) -> str:
    source_group = record.get("source_group", "")
    provider = record.get("provider", "")
    title = clean_text(record.get("title", "")).lower()
    if source_group == "research_papers":
        return "research_paper"
    if provider == "github" or clean_text(record.get("url", "")).startswith("https://github.com/"):
        return "community_tooling"
    if _matches_any(compact_text, UPDATE_PATTERNS):
        return "product_update"
    if _matches_any(compact_text, INFRA_PATTERNS):
        return "infrastructure_story"
    if _matches_any(compact_text, REACTION_PATTERNS):
        return "reaction_or_opinion"
    if source_group == "youtube_podcast_transcripts":
        return "tutorial_or_demo"
    if source_group == "ai_company_blogs":
        if title.startswith(("how ", "build ", "building ", "guide ", "tutorial ")):
            return "tutorial_or_demo"
        return "official_update"
    if _matches_any(compact_text, TUTORIAL_PATTERNS):
        return "tutorial_or_demo"
    return "unknown"


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)
