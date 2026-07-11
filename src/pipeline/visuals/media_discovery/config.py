from __future__ import annotations


PACKAGE_TYPE = "visual_media_package"
NEXT_MODULE = "visuals.asset_resolver"

CONTEXT_IMAGE_RENDER_KIND = "context_image_scene"
BROLL_VIDEO_RENDER_KIND = "broll_video_scene"
MEDIA_RENDER_KINDS = {CONTEXT_IMAGE_RENDER_KIND, BROLL_VIDEO_RENDER_KIND}

DEFAULT_WIKIMEDIA_ENDPOINT = "https://commons.wikimedia.org/w/api.php"
DEFAULT_PEXELS_PHOTO_ENDPOINT = "https://api.pexels.com/v1/search"
DEFAULT_PEXELS_VIDEO_ENDPOINT = "https://api.pexels.com/videos/search"
DEFAULT_PIXABAY_PHOTO_ENDPOINT = "https://pixabay.com/api/"
DEFAULT_PIXABAY_VIDEO_ENDPOINT = "https://pixabay.com/api/videos/"
DEFAULT_USER_AGENT = "AIContentCreation/2.0 (visual-media-discovery)"
