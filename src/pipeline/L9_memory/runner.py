"""
L9 Memory — record approved scripts as approved-but-not-published memory.

Reads:
    output/{run_id}/run_manifest.json
    output/{run_id}/L8/verification_package.json

Writes:
    output/{run_id}/L9/memory_update.json
    output/{run_id}/L9/summary.json
    output/memory/rebuild_memory.json

LLM: no
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from src.config.paths import CURRENT_MANIFEST_PATH, OUTPUT_DIR, REBUILD_MEMORY_PATH
from src.pipeline.L9_memory.memory_store import apply_memory_update
from src.pipeline.L9_memory.update_builder import build_memory_update


IST = timezone(timedelta(hours=5, minutes=30))


def run(run_ref: str) -> Path:
    manifest = _load_manifest(run_ref)
    run_id = manifest["run_id"]
    print(f"[L9] Run: {run_id}")

    verification_package = _load_l8_verification_package(run_id)
    print(
        f"[L9] Input package: {verification_package.get('package_type', '')}  "
        f"status={verification_package.get('status', '')}"
    )

    memory_update = build_memory_update(manifest, verification_package)
    memory = apply_memory_update(memory_update, REBUILD_MEMORY_PATH)
    summary = _build_summary(memory_update, memory)

    out_dir = OUTPUT_DIR / run_id / "L9"
    out_dir.mkdir(parents=True, exist_ok=True)
    update_path = out_dir / "memory_update.json"
    summary_path = out_dir / "summary.json"
    update_path.write_text(json.dumps(memory_update, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        f"[L9] Memory status: {memory_update['memory_status']}  "
        f"stories={summary['stories_recorded']}  sources={summary['sources_recorded']}"
    )
    print(f"[L9] Durable memory: {REBUILD_MEMORY_PATH}")
    print(f"[L9] Wrote: {update_path}")
    return update_path


def _build_summary(memory_update: dict, memory: dict) -> dict:
    return {
        "run_id": memory_update["run_id"],
        "generated_at": _iso_now(),
        "status": memory_update["status"],
        "package_type": memory_update["package_type"],
        "memory_status": memory_update["memory_status"],
        "publish_status": memory_update["publish_sync"]["publish_status"],
        "videos_in_memory": memory["stats"]["video_count"],
        "stories_recorded": len(memory_update["story_memory"]),
        "sources_recorded": len(memory_update["source_memory"]),
        "title_angles_recorded": len(memory_update["video_memory"].get("title_options", [])),
        "durable_memory_path": str(REBUILD_MEMORY_PATH),
        "memory_stats": memory["stats"],
    }


def _load_manifest(run_ref: str) -> dict:
    if run_ref == "current":
        path = CURRENT_MANIFEST_PATH
    else:
        path = OUTPUT_DIR / run_ref / "run_manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"Run manifest not found: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if run_ref == "current":
        run_id = manifest.get("run_id")
        if not run_id:
            raise KeyError("output/current_manifest.json is missing run_id")
        run_manifest_path = OUTPUT_DIR / run_id / "run_manifest.json"
        if not run_manifest_path.exists():
            raise FileNotFoundError(f"Run manifest not found: {run_manifest_path}")
        manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    return manifest


def _load_l8_verification_package(run_id: str) -> dict:
    path = OUTPUT_DIR / run_id / "L8" / "verification_package.json"
    if not path.exists():
        raise FileNotFoundError(f"L8 verification_package.json not found: {path}")
    package = json.loads(path.read_text(encoding="utf-8"))
    if package.get("package_type") != "roundup_verification":
        raise NotImplementedError("Layer 9 v1 supports only L8 package_type='roundup_verification'")
    return package


def _iso_now() -> str:
    return datetime.now(IST).isoformat()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="current")
    args = parser.parse_args()
    run(args.run_id)
