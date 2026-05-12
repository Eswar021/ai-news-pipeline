"""
Layer 10 — Module 13: Learning Signal Builder

Derives learning signals from current memory state.
This builder now rebuilds the full signal file from current memory so published
state and analytics updates can refresh downstream guidance.

Signals generated:
  - topic_coverage:  topics appearing most frequently across runs
  - entity_coverage: entities appearing most frequently across runs
  - source_quality:  tier-1 sources with high claim yield
  - format_pattern:  which formats have been used
  - open_followups:  count of open follow-up opportunities per topic

Output: memory/learning_signals.jsonl (rewritten from current state)
"""

import json
from collections import Counter
from datetime import datetime, timezone
from config.time_utils import now_project_iso
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


def _published_video_ids(video_records: list[dict]) -> set[str]:
    return {
        rec.get("video_id", "")
        for rec in video_records
        if rec.get("timestamps", {}).get("published_at")
    }


def build(mc: dict, ctx: dict, memory_dir: Path) -> dict:
    run_id = ctx.get("run_id", "memory_rebuild")
    now    = now_project_iso()

    # Load current state of memory files
    entity_topic_records = _load_jsonl(memory_dir / "entity_topic_memory.jsonl")
    source_records       = _load_jsonl(memory_dir / "source_memory.jsonl")
    video_records        = _load_jsonl(memory_dir / "video_memory.jsonl")
    followup_records     = _load_jsonl(memory_dir / "followups.jsonl")
    editorial_records    = _load_jsonl(memory_dir / "editorial_pattern_memory.jsonl")
    performance_records  = _load_jsonl(memory_dir / "performance_memory.jsonl")

    path     = memory_dir / "learning_signals.jsonl"
    published_ids = _published_video_ids(video_records)
    published_entity_topic_records = [
        r for r in entity_topic_records
        if r.get("coverage_update", {}).get("video_id", "") in published_ids
    ]
    published_source_records = [
        r for r in source_records
        if r.get("video_id", "") in published_ids
    ]
    performance_map = {
        r.get("video_id", ""): r
        for r in performance_records
        if r.get("video_id")
    }
    editorial_map = {
        r.get("video_id", ""): r
        for r in editorial_records
        if r.get("video_id")
    }

    signals = []

    # ── Signal 1: Topic coverage frequency ────────────────────────────────────
    topic_counts = Counter(
        r["entity_or_topic"]
        for r in published_entity_topic_records
        if r.get("memory_type") == "topic"
    )
    for topic, count in topic_counts.most_common():
        sig_id = f"sig_topic_{topic.lower().replace(' ', '_')}"
        signals.append({
            "learning_signal_id": sig_id,
            "run_id":             run_id,
            "signal_type":        "topic_coverage",
            "signal": {
                "topic":             topic,
                "times_covered":     count,
                "performance_trend": "unknown",
                "confidence":        "medium" if count else "low",
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
        for r in published_entity_topic_records
        if r.get("memory_type") == "entity"
    )
    for entity, count in entity_counts.most_common():
        sig_id = f"sig_entity_{entity.lower().replace(' ', '_')}"
        signals.append({
            "learning_signal_id": sig_id,
            "run_id":             run_id,
            "signal_type":        "entity_coverage",
            "signal": {
                "entity":            entity,
                "times_covered":     count,
                "performance_trend": "unknown",
                "confidence":        "medium" if count else "low",
            },
            "future_guidance": {
                "watch_for_followups":          True,
                "avoid_same_angle":             count >= 1,
                "potential_comparison_subject": entity in ("OpenAI", "Anthropic", "Google"),
            },
            "created_at": now,
        })

    # ── Signal 3: Source quality (tier-1 sources) ──────────────────────────────
    tier1_sources = [r for r in published_source_records if r.get("trust_tier") == 1]
    domain_claim_counts = Counter(r["domain"] for r in tier1_sources)
    for domain, count in domain_claim_counts.most_common():
        sig_id = f"sig_source_{domain.replace('.', '_')}"
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
    published_videos = [r for r in video_records if r.get("video_id", "") in published_ids]
    format_counts = Counter(r.get("selected_format", "") for r in published_videos)
    for fmt, count in format_counts.most_common():
        if not fmt:
            continue
        sig_id = f"sig_format_{fmt}"
        signals.append({
            "learning_signal_id": sig_id,
            "run_id":             run_id,
            "signal_type":        "format_distribution",
            "signal": {
                "format":            fmt,
                "times_used":        count,
                "performance_trend": "unknown",
                "confidence":        "medium" if count else "low",
            },
            "future_guidance": {
                "consider_format_variety": count >= 2,
            },
            "created_at": now,
        })

    # ── Signal 5: Open follow-up count ────────────────────────────────────────
    open_followups = [r for r in followup_records if r.get("status") == "open"]
    if open_followups:
        signals.append({
            "learning_signal_id": "sig_open_followups_summary",
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

    # ── Signal 6: Performance highlights ──────────────────────────────────────
    best_by_views = sorted(
        [r for r in performance_records if (r.get("performance", {}).get("views_48h") or 0) > 0],
        key=lambda r: r.get("performance", {}).get("views_48h") or 0,
        reverse=True,
    )[:5]
    for rec in best_by_views:
        attrs = rec.get("content_attributes", {})
        perf = rec.get("performance", {})
        signals.append({
            "learning_signal_id": f"sig_perf_{rec.get('video_id', '')}",
            "run_id": run_id,
            "signal_type": "performance_highlight",
            "signal": {
                "video_id": rec.get("video_id", ""),
                "format": attrs.get("format", ""),
                "views_48h": perf.get("views_48h"),
                "ctr": perf.get("ctr"),
                "average_view_duration_seconds": perf.get("average_view_duration_seconds"),
                "confidence": "high" if rec.get("window_complete") else "medium",
            },
            "future_guidance": {
                "preferred_topic": attrs.get("topics", [None])[0],
                "preferred_entity": attrs.get("entities", [None])[0],
                "preferred_hook_type": attrs.get("hook_type", ""),
                "preferred_title_angle": attrs.get("title_angle", ""),
            },
            "created_at": now,
        })

    # Write all signals from current state
    with open(path, "w", encoding="utf-8") as f:
        for sig in signals:
            f.write(json.dumps(sig) + "\n")

    return {
        "status":          "rebuilt",
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
