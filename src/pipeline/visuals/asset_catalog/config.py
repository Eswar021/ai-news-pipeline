from __future__ import annotations


PACKAGE_TYPE = "visual_asset_catalog"
NEXT_MODULE = "visuals.planner"
CATALOG_VERSION = "visual_asset_catalog_v2"

SOURCE_PAGE_ASSET = "source_page"
SOURCE_IMAGE_ASSET = "source_image"
SOURCE_VIDEO_ASSET = "source_video"
LOGO_ASSET = "logo"

EXTERNAL_REQUEST_TYPES = {
    "context_photo",
    "broll_video",
    "official_product_interface",
    "source_figure",
    "analogy_image",
}

NO_EXTERNAL_ASSET_TYPES = {
    "code_graphic",
    "kinetic_text",
    "transition",
}
