"""asset_collection: fetch this production's real source assets ONCE, in the content
stage, and persist them as a first-class artifact.

Runs right after video_packaging, so it collects assets for exactly the stories this
format uses (roundup's set, or the deep-dive's single topic). The visuals stage reads
this pool instead of re-fetching at render time, and the art-director draws its real
imagery from it. Best-effort and non-blocking: any failure degrades to an empty pool
with status "ok" — source imagery is an enhancement, never a reason to fail a run.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .collector import SCHEMA_VERSION, build_asset_manifest


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _empty_manifest() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "stories": []}


def run(input_json: dict) -> dict:
    run_req = input_json.get("run") if isinstance(input_json.get("run"), dict) else {}
    config = input_json.get("config") if isinstance(input_json.get("config"), dict) else {}
    inp = input_json.get("input") if isinstance(input_json.get("input"), dict) else {}
    run_id = str(run_req.get("run_id") or "")
    generated_at = _iso_now()

    packet = ((inp.get("video_packaging") or {}).get("data") or {}).get("video_packet") or {}
    stories = packet.get("stories") or []

    manifest = _empty_manifest()
    reason = ""
    if not bool(config.get("enabled", True)):
        reason = "asset_collection disabled"
    elif not stories:
        reason = "no stories in packet"
    else:
        try:
            manifest = build_asset_manifest(
                stories,
                timeout_seconds=float(config.get("timeout_seconds", 8.0)),
                max_images_per_story=int(config.get("max_images_per_story", 4)),
                max_attempts=int(config.get("max_attempts", 3)),
            )
        except Exception as exc:  # noqa: BLE001 — imagery is optional; never break the run
            reason = f"collection failed, degraded to empty: {type(exc).__name__}: {exc}"
            manifest = _empty_manifest()

    image_count = sum(len(s.get("images", [])) for s in manifest.get("stories", []))
    return {
        "status": "ok",
        "data": {
            "run_id": run_id,
            "generated_at": generated_at,
            "asset_manifest": manifest,
            "image_count": image_count,
            "story_count": len(manifest.get("stories", [])),
        },
        "summary": {
            "image_count": image_count,
            "stories_with_images": len(manifest.get("stories", [])),
            "reason": reason,
        },
        "handoff": {"ready_for_topic_research": True},
    }
