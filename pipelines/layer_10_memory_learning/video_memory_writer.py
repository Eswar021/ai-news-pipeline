"""
Layer 10 — Module 4: Video Memory Writer

Appends one record to memory/video_memory.jsonl.

Dedup key: video_id — skips if already present for this video_id.

Record structure:
  video_id, run_id, status, selected_format
  title: { working_title, approved_titles }
  coverage: { story_ids, entities, topics, used_claim_ids }
  assets: { verified_script_path, final_publish_package_path }
  verification: { l9_status, risk_level, remaining_warnings }
  timestamps: { created_at }
"""

import json
from datetime import datetime, timezone
from config.time_utils import now_project_iso
from pathlib import Path


def _load_existing(path: Path) -> list:
    if not path.exists() or path.stat().st_size == 0:
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def write(mc: dict, ctx: dict, eligibility: dict, memory_dir: Path) -> dict:
    if not eligibility["video_memory_allowed"]:
        return {"status": "skipped", "reason": eligibility["status"]}

    path      = memory_dir / "video_memory.jsonl"
    existing  = _load_existing(path)
    video_id  = mc["video_id"]

    if any(r["video_id"] == video_id for r in existing):
        return {"status": "skipped", "reason": "duplicate_video_id", "video_id": video_id}

    run_id     = ctx["run_id"]
    vr         = ctx["verification_report"]
    layer9_dir = ctx["layer9_dir"]
    fpp        = ctx["final_publish_package"]
    risk_level = vr.get("summary", {}).get("overall_risk_level", "")
    remaining  = vr.get("summary", {}).get("medium_issue_count", 0)

    record = {
        "video_id":        video_id,
        "selected_video_id": mc.get("selected_video_id", video_id),
        "run_id":          run_id,
        "status":          "prepared_for_human_review",
        "selected_format": mc["selected_format"],
        "title": {
            "working_title":   mc["working_title"],
            "approved_titles": mc["approved_titles"],
        },
        "coverage": {
            "story_ids":       mc["story_ids"],
            "entities":        mc["entities"],
            "topics":          mc["topics"],
            "used_claim_ids":  mc["used_claim_ids"],
        },
        "assets": {
            "verified_script_path":      str(layer9_dir / "verified_script.md"),
            "final_publish_package_path": str(layer9_dir / "final_publish_package.json"),
        },
        "publishing": {
            "platform": "youtube",
            "channel_id": None,
            "channel_title": None,
            "youtube_video_id": None,
            "video_url": None,
            "last_synced_at": None,
        },
        "verification": {
            "l9_status":          eligibility["l9_approval_status"],
            "risk_level":         risk_level,
            "remaining_warnings": remaining,
        },
        "timestamps": {
            "created_at":   now_project_iso(),
            "published_at": None,
        },
    }

    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    return {"status": "written", "video_id": video_id, "path": str(path)}


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
    print(f"Status   : {result['status']}")
    print(f"video_id : {result.get('video_id')}")
    print(f"Path     : {result.get('path')}")

    # Verify
    record = json.loads(open(MEMORY_DIR / "video_memory.jsonl").readlines()[-1])
    print(f"\nWritten record:")
    print(f"  video_id   : {record['video_id']}")
    print(f"  format     : {record['selected_format']}")
    print(f"  title      : {record['title']['working_title']}")
    print(f"  stories    : {len(record['coverage']['story_ids'])}")
    print(f"  entities   : {record['coverage']['entities']}")
    print(f"  topics     : {record['coverage']['topics']}")
    print(f"  claims used: {len(record['coverage']['used_claim_ids'])}")
    print(f"  l9_status  : {record['verification']['l9_status']}")
