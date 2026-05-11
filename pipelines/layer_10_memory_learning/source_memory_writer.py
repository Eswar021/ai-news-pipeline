"""
Layer 10 — Module 8: Source Reliability Memory Writer

Appends one record per source URL to memory/source_memory.jsonl.

Dedup key: url + run_id — skips if already recorded for this run.

Trust tier derived from domain:
  Tier 1: official company blogs/news (openai.com, anthropic.com, deepmind.google)
  Tier 2: established tech/AI media (techcrunch.com, wired.com, theverge.com, venturebeat.com)
  Tier 3: community/aggregators (reddit.com, news.ycombinator.com, twitter.com)
  Tier 4: everything else
"""

import json
from datetime import datetime, timezone
from pathlib import Path


_TIER1_DOMAINS = {
    "openai.com", "anthropic.com", "deepmind.google", "deepmind.com",
    "google.com", "microsoft.com", "meta.ai", "mistral.ai", "cohere.com",
    "huggingface.co", "stability.ai",
}
_TIER2_DOMAINS = {
    "techcrunch.com", "wired.com", "theverge.com", "venturebeat.com",
    "arstechnica.com", "zdnet.com", "technologyreview.com", "nature.com",
    "reuters.com", "bloomberg.com", "wsj.com", "ft.com", "nytimes.com",
    "theatlantic.com", "spectrum.ieee.org",
}
_TIER3_DOMAINS = {
    "reddit.com", "news.ycombinator.com", "twitter.com", "x.com",
    "linkedin.com", "medium.com", "substack.com",
}


def _get_trust_tier(domain: str) -> int:
    d = domain.lower().lstrip("www.")
    if any(d == t or d.endswith("." + t) for t in _TIER1_DOMAINS):
        return 1
    if any(d == t or d.endswith("." + t) for t in _TIER2_DOMAINS):
        return 2
    if any(d == t or d.endswith("." + t) for t in _TIER3_DOMAINS):
        return 3
    return 4


def _get_source_role(trust_tier: int) -> str:
    if trust_tier == 1:
        return "primary_evidence"
    if trust_tier == 2:
        return "secondary_evidence"
    if trust_tier == 3:
        return "trend_signal_only"
    return "supplementary"


def _load_existing_keys(path: Path) -> set:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            r = json.loads(line)
            keys.add((r["url"], r["run_id"]))
    return keys


def write(mc: dict, ctx: dict, eligibility: dict, memory_dir: Path) -> dict:
    if not eligibility["source_memory_allowed"]:
        return {"status": "skipped", "reason": eligibility["status"]}

    path          = memory_dir / "source_memory.jsonl"
    existing_keys = _load_existing_keys(path)
    run_id        = ctx["run_id"]
    video_id      = mc["video_id"]
    now           = datetime.now(timezone.utc).isoformat()

    # Count claims per domain for this run
    domain_claims: dict[str, list] = {}
    for src in mc["sources"]:
        domain = src.get("domain", "")
        claim_id = src.get("claim_id", "")
        if domain not in domain_claims:
            domain_claims[domain] = []
        if claim_id:
            domain_claims[domain].append(claim_id)

    written = []
    skipped = []

    with open(path, "a", encoding="utf-8") as f:
        seen_domains_this_run = set()
        for src in mc["sources"]:
            url    = src.get("url", "")
            domain = src.get("domain", "")

            if (url, run_id) in existing_keys:
                skipped.append(url)
                continue

            trust_tier = _get_trust_tier(domain)
            role       = _get_source_role(trust_tier)
            claims_for = domain_claims.get(domain, [])

            record = {
                "url":        url,
                "domain":     domain,
                "run_id":     run_id,
                "video_id":   video_id,
                "trust_tier": trust_tier,
                "source_role": role,
                "usage": {
                    "claim_ids":    claims_for,
                    "claim_count":  len(claims_for),
                    "used_in_script": True,
                },
                "collection_priority": "high" if trust_tier == 1 else ("medium" if trust_tier == 2 else "low"),
                "created_at": now,
            }
            f.write(json.dumps(record) + "\n")
            written.append(url)

    return {
        "status":  "written",
        "written": len(written),
        "skipped": len(skipped),
    }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from config.paths import RUNS_DIR, MEMORY_DIR
    from pipelines.layer_10_memory_learning.context_loader import load
    from pipelines.layer_10_memory_learning.eligibility_gate import gate
    from pipelines.layer_10_memory_learning.memory_context_extractor import extract

    run_id = "run_2026_05_10_48h_auto"
    base   = RUNS_DIR / run_id
    ctx    = load(base / "layer_9", base / "layer_8", base / "layer_7",
                  base / "layer_5", base / "layer_4", base / "layer_3")
    elig   = gate(ctx)
    mc     = extract(ctx)
    result = write(mc, ctx, elig, MEMORY_DIR)
    print(f"Status  : {result['status']}")
    print(f"Written : {result['written']}  Skipped: {result['skipped']}")

    records = []
    with open(MEMORY_DIR / "source_memory.jsonl") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    print(f"\nTotal records: {len(records)}")
    for r in records:
        print(f"  [tier {r['trust_tier']}] {r['domain']:30}  role={r['source_role']:20}  claims={r['usage']['claim_count']}")
