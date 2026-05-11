"""
Layer 10 — Module 13: Learning Signal Builder

Derives frequency-based learning signals from current memory state.
No YouTube performance data yet — confidence = "low" on all signals.

Signals generated:
  - topic_coverage:  topics appearing most frequently across runs
  - entity_coverage: entities appearing most frequently across runs
  - source_quality:  tier-1 sources with high claim yield
  - format_pattern:  which formats have been used
  - open_followups:  count of open follow-up opportunities per topic

Output: memory/learning_signals.jsonl (appends)
"""

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def _load_jsonl(path: Path) -> list:
    if not path.exists() or path.stat().st_size == 0:
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def _load_existing_signal_ids(path: Path) -> set:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    ids = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            ids.add(json.loads(line).get("learning_signal_id", ""))
    return ids


def build(mc: dict, ctx: dict, memory_dir: Path) -> dict:
    run_id = ctx["run_id"]
    now    = datetime.now(timezone.utc).isoformat()

    # Load current state of memory files
    entity_topic_records = _load_jsonl(memory_dir / "entity_topic_memory.jsonl")
    source_records       = _load_jsonl(memory_dir / "source_memory.jsonl")
    video_records        = _load_jsonl(memory_dir / "video_memory.jsonl")
    followup_records     = _load_jsonl(memory_dir / "followups.jsonl")

    path     = memory_dir / "learning_signals.jsonl"
    existing = _load_existing_signal_ids(path)

    signals  = []

    # ── Signal 1: Topic coverage frequency ────────────────────────────────────
    topic_counts = Counter(
        r["entity_or_topic"]
        for r in entity_topic_records
        if r.get("memory_type") == "topic"
    )
    for topic, count in topic_counts.most_common():
        sig_id = f"sig_topic_{topic.lower().replace(' ', '_')}_{run_id[-6:]}"
        if sig_id in existing:
            continue
        signals.append({
            "learning_signal_id": sig_id,
            "run_id":             run_id,
            "signal_type":        "topic_coverage",
            "signal": {
                "topic":             topic,
                "times_covered":     count,
                "performance_trend": "unknown",
                "confidence":        "low",
            },
            "future_guidance": {
                "increase_priority_in_layer5": count >= 2,
                "recommended_formats":         ["follow_up", "evergreen"] if count >= 2 else ["roundup"],
                "avoid_repeating_same_angle":  count >= 1,
            },
            "created_at": now,
        })

    # ── Signal 2: Entity coverage frequency ───────────────────────────────────
    entity_counts = Counter(
        r["entity_or_topic"]
        for r in entity_topic_records
        if r.get("memory_type") == "entity"
    )
    for entity, count in entity_counts.most_common():
        sig_id = f"sig_entity_{entity.lower().replace(' ', '_')}_{run_id[-6:]}"
        if sig_id in existing:
            continue
        signals.append({
            "learning_signal_id": sig_id,
            "run_id":             run_id,
            "signal_type":        "entity_coverage",
            "signal": {
                "entity":            entity,
                "times_covered":     count,
                "performance_trend": "unknown",
                "confidence":        "low",
            },
            "future_guidance": {
                "watch_for_followups":          True,
                "avoid_same_angle":             count >= 1,
                "potential_comparison_subject": entity in ("OpenAI", "Anthropic", "Google"),
            },
            "created_at": now,
        })

    # ── Signal 3: Source quality (tier-1 sources) ──────────────────────────────
    tier1_sources = [r for r in source_records if r.get("trust_tier") == 1]
    domain_claim_counts = Counter(r["domain"] for r in tier1_sources)
    for domain, count in domain_claim_counts.most_common():
        sig_id = f"sig_source_{domain.replace('.', '_')}_{run_id[-6:]}"
        if sig_id in existing:
            continue
        signals.append({
            "learning_signal_id": sig_id,
            "run_id":             run_id,
            "signal_type":        "source_quality",
            "signal": {
                "domain":           domain,
                "trust_tier":       1,
                "times_used":       count,
                "usefulness":       "high",
                "confidence":       "medium",
            },
            "future_guidance": {
                "increase_collection_priority": True,
                "use_as_primary_evidence":      True,
            },
            "created_at": now,
        })

    # ── Signal 4: Format distribution ─────────────────────────────────────────
    format_counts = Counter(r.get("selected_format", "") for r in video_records)
    for fmt, count in format_counts.most_common():
        if not fmt:
            continue
        sig_id = f"sig_format_{fmt}_{run_id[-6:]}"
        if sig_id in existing:
            continue
        signals.append({
            "learning_signal_id": sig_id,
            "run_id":             run_id,
            "signal_type":        "format_distribution",
            "signal": {
                "format":            fmt,
                "times_used":        count,
                "performance_trend": "unknown",
                "confidence":        "low",
            },
            "future_guidance": {
                "consider_format_variety": count >= 2,
            },
            "created_at": now,
        })

    # ── Signal 5: Open follow-up count ────────────────────────────────────────
    open_followups = [r for r in followup_records if r.get("status") == "open"]
    if open_followups:
        sig_id = f"sig_open_followups_{run_id[-6:]}"
        if sig_id not in existing:
            signals.append({
                "learning_signal_id": sig_id,
                "run_id":             run_id,
                "signal_type":        "open_followups_summary",
                "signal": {
                    "open_followup_count": len(open_followups),
                    "confidence":          "medium",
                },
                "future_guidance": {
                    "check_followup_list_before_layer5":  True,
                    "prioritize_stories_with_new_evidence": True,
                },
                "created_at": now,
            })

    # Write all signals
    with open(path, "a", encoding="utf-8") as f:
        for sig in signals:
            f.write(json.dumps(sig) + "\n")

    return {
        "status":          "written",
        "signals_written": len(signals),
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
    result = build(mc, ctx, MEMORY_DIR)
    print(f"Status  : {result['status']}")
    print(f"Signals : {result['signals_written']}")

    records = []
    with open(MEMORY_DIR / "learning_signals.jsonl") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    print(f"\nTotal signal records: {len(records)}")
    for r in records:
        sig = r["signal"]
        key = sig.get("topic") or sig.get("entity") or sig.get("domain") or sig.get("format") or r["signal_type"]
        print(f"  [{r['signal_type']:25}] {key}")
