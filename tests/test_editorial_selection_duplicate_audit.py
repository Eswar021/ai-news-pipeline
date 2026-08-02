"""editorial_selection focused duplicate audit: tolerate benign repeated members.

Regression for a production failure where the audit LLM returned a duplicate
group listing the same story twice, and the strict validator failed the whole
selection after bounded retries instead of de-duping the harmless repeat.
"""
from __future__ import annotations

from src.pipeline.content.editorial_selection.formats.roundup.app import (
    _restore_duplicate_audit_story_ids,
    _validate_duplicate_audit,
)
from src.pipeline.content.editorial_selection.formats.roundup.contract import (
    RoundupDuplicateAudit,
)

REF_MAP = {"s1": "story_alpha", "s2": "story_beta", "s3": "story_gamma"}
STORIES = [{"story_id": name} for name in ("story_alpha", "story_beta", "story_gamma")]


def _audit(group_story_ids: list[str], assessments: list[tuple[str, str]]) -> RoundupDuplicateAudit:
    return RoundupDuplicateAudit.model_validate(
        {
            "assessments": [
                {"story_id": ref, "event_summary": "e", "duplicate_group_id": gid, "reason": "r"}
                for ref, gid in assessments
            ],
            "duplicate_story_groups": [
                {
                    "group_id": "group_001",
                    "story_ids": group_story_ids,
                    "relationship": "same_event",
                    "preferred_story_id": group_story_ids[0],
                    "reason": "r",
                }
            ],
            "audit_summary": "s",
        }
    )


def test_repeated_member_in_a_real_group_is_deduped_not_failed() -> None:
    audit = _audit(["s1", "s2", "s1"], [("s1", "group_001"), ("s2", "group_001"), ("s3", "")])
    restored = _restore_duplicate_audit_story_ids(audit, REF_MAP)
    assert restored.duplicate_story_groups[0].story_ids == ["story_alpha", "story_beta"]
    _validate_duplicate_audit(restored, STORIES)  # must not raise


def test_group_collapsing_below_two_members_is_dropped() -> None:
    audit = _audit(["s1", "s1"], [("s1", "group_001"), ("s2", ""), ("s3", "")])
    restored = _restore_duplicate_audit_story_ids(audit, REF_MAP)
    assert restored.duplicate_story_groups == []
    lone = next(a for a in restored.assessments if a.story_id == "story_alpha")
    assert lone.duplicate_group_id == ""
    _validate_duplicate_audit(restored, STORIES)  # must not raise
