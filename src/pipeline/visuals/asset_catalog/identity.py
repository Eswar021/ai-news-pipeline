from __future__ import annotations

from typing import Any


def catalog_identity_payload(catalog: dict[str, Any]) -> dict[str, Any]:
    return {
        "catalog_version": catalog.get("catalog_version"),
        "research_mode": catalog.get("research_mode"),
        "assets": [
            {
                "asset_id": asset.get("asset_id"),
                "story_id": asset.get("story_id"),
                "asset_type": asset.get("asset_type"),
                "status": asset.get("status"),
                "source_record_key": asset.get("source_record_key"),
                "source_url": asset.get("source_url"),
                "asset_url": asset.get("asset_url"),
                "content_sha256": asset.get("content_sha256", ""),
            }
            for asset in catalog.get("assets", [])
            if isinstance(asset, dict)
        ],
        "story_asset_briefs": [
            {
                "story_id": story.get("story_id"),
                "asset_briefs": story.get("asset_briefs", []),
            }
            for story in catalog.get("story_catalogs", [])
            if isinstance(story, dict)
        ],
    }
