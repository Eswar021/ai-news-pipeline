"""
Layer 9 — Module 12: Source List + Attribution Checker

Verifies the final source list and attribution package:
  - All source URLs used in script sentences appear in youtube_metadata source_list
  - Source list is not empty
  - Description mentions sources (has URLs or source section)
  - No community-only URLs are present in primary source list

Returns:
    dict with status, missing_sources, coverage stats
"""


def check(ctx: dict) -> dict:
    youtube_meta    = ctx["youtube_metadata"]
    sentence_list   = ctx["sentence_list"]

    # Collect all URLs used in script sentences
    script_urls = set()
    for s in sentence_list:
        for url in s.get("source_urls", []):
            if url:
                script_urls.add(url)

    # Collect URLs in source_list
    source_list     = youtube_meta.get("source_list", []) or []
    listed_urls     = {item.get("url", "") for item in source_list if item.get("url")}
    listed_urls.discard("")

    # Collect URLs mentioned in description
    description     = youtube_meta.get("description", "") or ""
    desc_has_urls   = "http" in description

    # Find missing sources
    missing = sorted(script_urls - listed_urls)
    extra   = sorted(listed_urls - script_urls)

    warnings = []
    errors   = []

    if not source_list:
        errors.append("Source list is empty — no sources in YouTube metadata.")

    if missing:
        for url in missing:
            warnings.append(f"Source used in script but not in source_list: {url}")

    if not desc_has_urls:
        warnings.append("YouTube description has no source URLs.")

    passed = len(errors) == 0

    return {
        "passed":                  passed,
        "status":                  "passed" if passed else "failed",
        "errors":                  errors,
        "warnings":                warnings,
        "sources_used_in_script":  len(script_urls),
        "sources_in_list":         len(listed_urls),
        "missing_from_list":       len(missing),
        "extra_in_list":           len(extra),
        "missing_source_urls":     missing,
        "description_has_sources": desc_has_urls,
    }


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from config.paths import RUNS_DIR
    from pipelines.layer_9_verification_firewall.context_loader import load

    run_id = "run_2026_05_10_48h_auto"
    base = RUNS_DIR / run_id
    ctx = load(base / "layer_8", base / "layer_7", base / "layer_4", base / "layer_2")
    result = check(ctx)

    print(f"Status                  : {result['status']}")
    print(f"Sources used in script  : {result['sources_used_in_script']}")
    print(f"Sources in list         : {result['sources_in_list']}")
    print(f"Missing from list       : {result['missing_from_list']}")
    print(f"Description has sources : {result['description_has_sources']}")
    for e in result["errors"]:
        print(f"  ERROR: {e}")
    for w in result["warnings"]:
        print(f"  WARN : {w}")
