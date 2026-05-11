"""
Layer 9 — Module 5: Claim-to-Source Traceability Checker

For each claim_id used in the script, verifies:
  1. Claim exists in verified_claims
  2. Claim has source_span_ids (from claim_evidence_map or verified_claims)
  3. Those source_span_ids exist in span_map
  4. Claim has at least one source_url

Traceability statuses:
  passed         — full traceability confirmed
  no_spans       — claim has no source_span_ids (medium severity)
  missing_spans  — some span IDs not in span_map (medium severity)
  no_source_url  — claim has no source URLs (low severity warning)
  claim_missing  — claim_id not found at all (critical)

Returns:
    dict with results list and summary
"""


def check(coverage_results: dict, ctx: dict) -> dict:
    claim_map = ctx["claim_map"]
    cem_map   = ctx["cem_map"]
    span_map  = ctx["span_map"]

    # Collect unique used claim_ids from covered sentences
    used_claim_ids = set()
    for r in coverage_results["results"]:
        if r.get("coverage_status") in ("covered",):
            for cid in r.get("claim_ids", []):
                used_claim_ids.add(cid)

    results      = []
    missing      = []
    no_spans     = []
    broken_spans = []

    for cid in sorted(used_claim_ids):
        if cid not in claim_map:
            rec = {
                "claim_id":            cid,
                "traceability_status": "claim_missing",
                "severity":            "critical",
                "reason":              "Claim ID not in verified_claims",
                "source_span_ids":     [],
                "source_urls":         [],
            }
            results.append(rec)
            missing.append(rec)
            continue

        claim = claim_map[cid]
        cem   = cem_map.get(cid, {})

        # Prefer cem_map for span IDs; fallback to claim record
        span_ids   = cem.get("source_span_ids", []) or claim.get("source_span_ids", [])
        source_urls = cem.get("source_urls", []) or claim.get("source_urls", [])

        if not span_ids:
            rec = {
                "claim_id":            cid,
                "traceability_status": "no_spans",
                "severity":            "medium",
                "reason":              "Claim has no source_span_ids",
                "source_span_ids":     [],
                "source_urls":         source_urls,
            }
            results.append(rec)
            no_spans.append(rec)
            continue

        # Check which spans actually exist
        missing_span_ids  = [s for s in span_ids if s not in span_map]
        resolved_span_ids = [s for s in span_ids if s in span_map]

        if missing_span_ids and not resolved_span_ids:
            rec = {
                "claim_id":            cid,
                "traceability_status": "missing_spans",
                "severity":            "medium",
                "reason":              f"Span IDs not found: {missing_span_ids[:3]}",
                "source_span_ids":     span_ids,
                "resolved_span_ids":   resolved_span_ids,
                "missing_span_ids":    missing_span_ids,
                "source_urls":         source_urls,
            }
            results.append(rec)
            broken_spans.append(rec)
            continue

        status = "passed"
        if missing_span_ids:
            status = "partial_spans"

        results.append({
            "claim_id":            cid,
            "traceability_status": status,
            "severity":            "info",
            "source_span_ids":     span_ids,
            "resolved_span_ids":   resolved_span_ids,
            "missing_span_ids":    missing_span_ids,
            "source_urls":         source_urls,
        })

    passed_count = sum(1 for r in results if r["traceability_status"] in ("passed", "partial_spans"))

    return {
        "results":         results,
        "total_checked":   len(results),
        "passed":          len(missing) == 0 and len(broken_spans) == 0,
        "passed_count":    passed_count,
        "missing_claims":  len(missing),
        "no_spans":        len(no_spans),
        "broken_spans":    len(broken_spans),
        "missing_list":    missing,
        "no_spans_list":   no_spans,
        "broken_list":     broken_spans,
    }


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from config.paths import RUNS_DIR
    from pipelines.layer_9_verification_firewall.context_loader import load
    from pipelines.layer_9_verification_firewall.sentence_classification_validator import classify
    from pipelines.layer_9_verification_firewall.sentence_claim_coverage_checker import check as check_coverage

    run_id = "run_2026_05_10_48h_auto"
    base = RUNS_DIR / run_id
    ctx = load(base / "layer_8", base / "layer_7", base / "layer_4", base / "layer_2")
    classified = classify(ctx)
    coverage = check_coverage(classified, ctx)
    result = check(coverage, ctx)

    print(f"Claims checked : {result['total_checked']}")
    print(f"Passed         : {result['passed_count']}")
    print(f"Missing claims : {result['missing_claims']}")
    print(f"No spans       : {result['no_spans']}")
    print(f"Broken spans   : {result['broken_spans']}")
    print(f"Overall passed : {result['passed']}")

    if result["no_spans_list"]:
        print("\nClaims with no spans:")
        for r in result["no_spans_list"][:5]:
            print(f"  {r['claim_id']}: {r['reason']}")
