"""video_packaging deep_dive format: packet builder + format-dispatched router."""
from __future__ import annotations

import pytest

from src.pipeline.content.video_packaging.app import run as run_video_packaging
from src.pipeline.content.video_packaging.formats.deep_dive import build_deep_dive_packet


def _slate() -> dict:
    return {
        "episode_thesis": "One big shift in AI this week.",
        "ordering_rationale": "Lead is the most consequential story.",
        "selected_stories": [
            {"story_id": "story_lead", "editorial_selection": {"role": "lead"}, "records": [{"record_key": "r1"}, {"record_key": "r2"}]},
            {"story_id": "story_major", "editorial_selection": {"role": "major"}, "records": [{"record_key": "r3"}]},
        ],
        "reserve": [{"story_id": "story_reserve"}],
        "rejected": [{"story_id": "story_rej", "reason": "duplicate"}],
    }


def test_deep_dive_packet_expands_the_lead_story_only() -> None:
    out = build_deep_dive_packet(_slate(), {"story_selection": "lead", "min_stories": 1, "duration_ceiling_seconds": 420})
    packet = out["packet"]
    assert packet["packet_type"] == "deep_dive"
    assert packet["selected_format"] == "deep_dive"
    assert packet["script_app"] == "script_generation.formats.deep_dive"
    assert packet["story_count"] == 1
    assert packet["selected_story_ids"] == ["story_lead"]
    assert packet["stories"][0]["video_segment"]["source_record_keys"] == ["r1", "r2"]
    # Other selected stories stay available for a different derived format.
    assert packet["editorial_context"]["unexpanded_selected_story_ids"] == ["story_major"]
    assert out["selection_stats"]["selected_story_count"] == 1


def test_deep_dive_requires_records_on_the_chosen_story() -> None:
    slate = _slate()
    slate["selected_stories"][0]["records"] = []
    with pytest.raises(ValueError):
        build_deep_dive_packet(slate, {"story_selection": "lead"})


def test_router_dispatches_deep_dive_format() -> None:
    request = {
        "run": {"run_id": "run_dd"},
        "config": {
            "target_format": "deep_dive",
            "deep_dive": {"story_selection": "lead", "min_stories": 1, "duration_ceiling_seconds": 480},
        },
        "input": {
            "editorial_selection": {
                "status": "ok",
                "data": {"editorial_slate": _slate()},
                "handoff": {"ready_for_video_packaging": True},
            }
        },
    }
    result = run_video_packaging(request)
    assert result["status"] == "ok"
    assert result["data"]["selected_format"] == "deep_dive"
    assert result["data"]["script_app"] == "script_generation.formats.deep_dive"
    assert result["data"]["video_packet"]["story_count"] == 1
    assert result["handoff"]["ready_for_script_generation"] is True
