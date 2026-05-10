"""
Layer 6 — Module 1: Brief Loader

Loads and validates the Layer 5 selected_video_brief.json and returns a
structured context dict consumed by all downstream Layer 6 modules.

Also resolves packet_type (roundup_packet / deep_dive_packet) so the
orchestrator can route to the correct builder.

Key function:
    load(layer5_dir) → brief_ctx dict

Individual test:
    python brief_loader.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.paths import RUNS_DIR

_SUPPORTED_FORMATS = {"roundup", "deep_dive"}


def load(layer5_dir: Path) -> dict:
    brief_path = layer5_dir / "selected_video_brief.json"
    with open(brief_path) as f:
        brief = json.load(f)

    selected_format = brief.get("selected_format", "")
    if selected_format not in _SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported format '{selected_format}'; expected one of {_SUPPORTED_FORMATS}")

    story_ids = brief.get("selected_story_ids") or []
    if not story_ids and brief.get("primary_story_id"):
        story_ids = [brief["primary_story_id"]]
    if not story_ids:
        raise ValueError("No selected story IDs in brief")

    eb = brief.get("evidence_boundaries", {})
    safe_ids = eb.get("safe_claim_ids", [])
    if not safe_ids:
        raise ValueError("evidence_boundaries.safe_claim_ids is empty")

    seg_by_story = {
        s["story_id"]: s
        for s in (brief.get("story_segment_guidance") or [])
    }

    return {
        "selected_video_id":      brief.get("selected_video_id", ""),
        "selected_format":        selected_format,
        "packet_type":            f"{selected_format}_packet",
        "selected_story_ids":     story_ids,
        "primary_story_id":       brief.get("primary_story_id"),
        "content_direction":      brief.get("content_direction", {}),
        "story_segment_guidance": brief.get("story_segment_guidance", []),
        "seg_by_story":           seg_by_story,
        "evidence_boundaries":    eb,
        "safe_claim_ids":         set(safe_ids),
        "cautious_claim_ids":     set(eb.get("cautious_claim_ids", [])),
        "do_not_use_claim_ids":   set(eb.get("do_not_use_claim_ids", [])),
        "format_guidance":        brief.get("format_guidance", {}),
    }


if __name__ == "__main__":
    run_id = sorted(RUNS_DIR.glob("*/layer_5/selected_video_brief.json"),
                    key=lambda p: p.stat().st_mtime, reverse=True)[0].parents[1].name
    layer5_dir = RUNS_DIR / run_id / "layer_5"
    ctx = load(layer5_dir)
    print(f"Run           : {run_id}")
    print(f"Format        : {ctx['selected_format']}")
    print(f"Packet type   : {ctx['packet_type']}")
    print(f"Stories       : {len(ctx['selected_story_ids'])}")
    print(f"Safe claims   : {len(ctx['safe_claim_ids'])}")
    print(f"Cautious      : {len(ctx['cautious_claim_ids'])}")
    print(f"Do-not-use    : {len(ctx['do_not_use_claim_ids'])}")
    print(f"Seg guidance  : {len(ctx['story_segment_guidance'])} entries")
    print(f"Content dir   : {list(ctx['content_direction'].keys())}")
