from __future__ import annotations

from pathlib import Path


PACKAGE_TYPE = "visual_render_package"
NEXT_MODULE = "video_assembly"
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_FPS = 30
DEFAULT_CODEC = "h264"

QUALITY_PRESETS = {
    "1080p": {
        "width": 1920,
        "height": 1080,
        "crf": 16,
        "x264_preset": "slow",
        "pixel_format": "yuv420p",
    },
    "2k": {
        "width": 2560,
        "height": 1440,
        "crf": 15,
        "x264_preset": "slow",
        "pixel_format": "yuv420p",
    },
    "4k": {
        "width": 3840,
        "height": 2160,
        "crf": 14,
        "x264_preset": "slow",
        "pixel_format": "yuv420p",
    },
}


def default_remotion_engine_dir() -> str:
    return str(Path(__file__).resolve().parents[1] / "remotion_engine")
