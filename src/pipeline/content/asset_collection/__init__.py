"""Best-effort source-image collection for the visuals stage."""
from __future__ import annotations

from .app import run
from .collector import build_asset_manifest, extract_image_url

__all__ = ["run", "build_asset_manifest", "extract_image_url"]
