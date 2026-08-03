"""Best-effort source-image collection for the visuals stage."""
from __future__ import annotations

from .collector import build_asset_manifest, extract_image_url

__all__ = ["build_asset_manifest", "extract_image_url"]
