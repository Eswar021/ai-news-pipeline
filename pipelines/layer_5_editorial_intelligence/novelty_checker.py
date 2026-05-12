"""
Layer 5 — Module 5: Novelty Checker

Checks whether each story has been covered before by comparing entities
and topics against video_memory.jsonl. Also detects follow-up opportunities
from followups.jsonl (merged from design module 5.8, since follow_up format
is disabled we just flag candidates without routing them).

Similarity signals:
  entity_overlap — Jaccard of companies + models vs previous video entities
  topic_overlap  — Jaccard of topics vs previous video topics

Coverage thresholds (from design doc novelty_rules):
  > 0.85 → already_covered
  > 0.55 → related_but_new
  else   → new_topic

Memory window: 60 days. Only published videos are considered, and videos older
than 60 days are ignored.

If memory is empty (first run), all stories get:
  novelty_score=90, coverage_status=new_topic

Key function:
    check_all(candidates, memory_dir) → list of novelty dicts

Usage:
    python novelty_checker.py --run-id run_2026_05_10_48h_auto
"""

import sys
import json
import re
import argparse
from datetime import datetime, timezone, timedelta
from config.time_utils import now_project
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR, ROOT

MEMORY_DIR = ROOT / "memory"

_DUPLICATE_THRESHOLD  = 0.85
_RELATED_THRESHOLD    = 0.55
_MEMORY_WINDOW_DAYS   = 60


def _tokens(text: str) -> frozenset:
    return frozenset(re.findall(r"[a-z0-9]+", text.lower()))


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    return len(a & b) / len(union)


def _entity_set(companies: list, models: list) -> frozenset:
    combined = companies + models
    return frozenset(c.lower().strip() for c in combined if c)


def _topic_set(topics: list) -> frozenset:
    result = set()
    for t in topics:
        result.update(re.findall(r"[a-z0-9]+", t.lower()))
    return frozenset(result)


def _load_video_memory(memory_dir: Path) -> list[dict]:
    path = memory_dir / "video_memory.jsonl"
    if not path.exists():
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _load_followup_memory(memory_dir: Path) -> list[dict]:
    path = memory_dir / "followups.jsonl"
    if not path.exists():
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _filter_recent(videos: list[dict]) -> list[dict]:
    cutoff = now_project() - timedelta(days=_MEMORY_WINDOW_DAYS)
    recent = []
    for v in videos:
        timestamps = v.get("timestamps", {})
        published = (
            timestamps.get("published_at")
            or v.get("published_at")
            or ""
        )
        if not published:
            continue
        try:
            dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
            if dt >= cutoff:
                recent.append(v)
        except (ValueError, AttributeError):
            continue
    return recent


def _check_follow_up(candidate: dict, followup_memory: list[dict]) -> dict | None:
    """Check if candidate entities/topics match an open follow-up item."""
    if not followup_memory:
        return None
    cand_entities = {c.lower() for c in candidate.get("companies", [])}
    cand_topics   = _topic_set(candidate.get("topics", []))
    for fu in followup_memory:
        fu_entities = {c.lower() for c in (fu.get("entities") or [])}
        fu_topics   = _topic_set(fu.get("topics") or [])
        entity_hit  = bool(cand_entities & fu_entities)
        topic_sim   = _jaccard(cand_topics, fu_topics)
        if entity_hit or topic_sim > 0.4:
            return {
                "video_id":        fu.get("video_id", "unknown"),
                "follow_up_type":  fu.get("follow_up_type", "trend_continuation"),
                "follow_up_score": min(int(topic_sim * 100) + 20, 85),
            }
    return None


def check(candidate: dict, recent_videos: list[dict],
          followup_memory: list[dict]) -> dict:
    sid = candidate["story_id"]

    # Empty memory → everything is new
    if not recent_videos:
        return {
            "story_id":        sid,
            "novelty_score":   90,
            "coverage_status": "new_topic",
            "previous_related_videos": [],
            "is_follow_up_candidate": False,
            "follow_up_info":  None,
            "recommendation":  "safe_to_cover",
        }

    cand_entities = _entity_set(
        candidate.get("companies", []),
        candidate.get("models", [])
    )
    cand_topics = _topic_set(candidate.get("topics", []))

    best_sim   = 0.0
    best_video = None
    related_videos = []

    for video in recent_videos:
        prev_entities = _entity_set(
            video.get("companies") or video.get("entities", {}).get("companies", []),
            video.get("models") or video.get("entities", {}).get("models", [])
        )
        prev_topics = _topic_set(
            video.get("topics") or []
        )
        entity_sim = _jaccard(cand_entities, prev_entities)
        topic_sim  = _jaccard(cand_topics, prev_topics)
        combined   = entity_sim * 0.6 + topic_sim * 0.4

        if combined > 0.3:
            related_videos.append({
                "video_id":        video.get("video_id", "unknown"),
                "similarity_score": round(combined, 2),
                "relationship":    (
                    "already_covered"            if combined >= _DUPLICATE_THRESHOLD else
                    "same_broad_topic"           if combined >= _RELATED_THRESHOLD else
                    "loosely_related"
                ),
            })
        if combined > best_sim:
            best_sim   = combined
            best_video = video

    related_videos.sort(key=lambda v: v["similarity_score"], reverse=True)

    if best_sim >= _DUPLICATE_THRESHOLD:
        coverage_status  = "already_covered"
        novelty_score    = max(10, int((1 - best_sim) * 100))
        recommendation   = "skip"
    elif best_sim >= _RELATED_THRESHOLD:
        coverage_status  = "related_but_new"
        novelty_score    = int((1 - best_sim) * 100) + 20
        recommendation   = "safe_to_cover_with_new_angle"
    else:
        coverage_status  = "new_topic"
        novelty_score    = 90
        recommendation   = "safe_to_cover"

    novelty_score = max(0, min(100, novelty_score))

    follow_up = _check_follow_up(candidate, followup_memory)

    return {
        "story_id":        sid,
        "novelty_score":   novelty_score,
        "coverage_status": coverage_status,
        "previous_related_videos": related_videos[:3],
        "is_follow_up_candidate": follow_up is not None,
        "follow_up_info":  follow_up,
        "recommendation":  recommendation,
    }


def check_all(candidates: list[dict], memory_dir: Path | None = None) -> list[dict]:
    if memory_dir is None:
        memory_dir = MEMORY_DIR
    video_memory    = _load_video_memory(memory_dir)
    followup_memory = _load_followup_memory(memory_dir)
    recent_videos   = _filter_recent(video_memory)
    return [check(c, recent_videos, followup_memory) for c in candidates]


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=False)
    args = parser.parse_args()

    run_id = args.run_id
    if not run_id:
        for rp in sorted(RUNS_DIR.glob("*/run_manifest.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True):
            if (rp.parent / "layer_4" / "story_fact_sheets.json").exists():
                run_id = rp.parent.name
                break
        print(f"Auto-discovered run: {run_id}")

    from pipelines.layer_5_editorial_intelligence.editorial_candidate_loader import load
    layer3_dir = RUNS_DIR / run_id / "layer_3"
    layer4_dir = RUNS_DIR / run_id / "layer_4"
    result     = load(run_id, layer3_dir, layer4_dir)
    candidates = result["editorial_candidates"]

    novelty_results = check_all(candidates)
    print(f"\nNovelty Checker — {run_id}")
    print(f"  Memory files: video_memory={len(_load_video_memory(MEMORY_DIR))} videos")
    for cand, nv in zip(candidates, novelty_results):
        fu_flag = " [follow-up]" if nv["is_follow_up_candidate"] else ""
        print(f"  {nv['novelty_score']:3d}  {nv['coverage_status']:<20}  "
              f"{cand['story_title'][:50]}{fu_flag}")
