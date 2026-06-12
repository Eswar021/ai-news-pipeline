from __future__ import annotations

from pathlib import Path


PACKAGE_TYPE = "visual_render_package"
NEXT_MODULE = "video_assembly"
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_FPS = 30
DEFAULT_CODEC = "h264"


def default_remotion_engine_dir() -> str:
    return str(Path(__file__).resolve().parents[1] / "remotion_engine")

