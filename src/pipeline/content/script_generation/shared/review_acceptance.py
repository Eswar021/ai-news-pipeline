from __future__ import annotations

from typing import Any


def story_review_beat_ids(segment: dict[str, Any]) -> list[str]:
    return [f"beat_{index:02d}" for index, _ in enumerate(segment.get("beats") or [], start=1)]


def bookend_review_beat_ids(bookends: dict[str, Any]) -> list[str]:
    anchors = [
        f"intro_beat_{index:02d}"
        for index, _ in enumerate(bookends.get("intro_beats") or [], start=1)
    ]
    anchors.extend(
        f"connector_{index:02d}"
        for index, _ in enumerate(bookends.get("story_connectors") or [], start=1)
    )
    anchors.extend(
        f"closing_beat_{index:02d}"
        for index, _ in enumerate(bookends.get("closing_beats") or [], start=1)
    )
    return anchors
