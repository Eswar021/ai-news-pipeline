from __future__ import annotations

from langchain_core.utils.function_calling import convert_to_openai_tool

from src.pipeline.content.editorial_selection.formats.roundup.contract import (
    CandidateScreenDraft,
    RoundupDuplicateAudit,
    RoundupSlateDraft,
    RoundupSlateReviewDraft,
)
from src.pipeline.content.editorial_triage.contract import TriageBatchOutput
from src.pipeline.content.metadata_creator.app import MetadataDraftOutput
from src.pipeline.content.script_generation.formats.roundup.models import (
    BookendReviewOutput,
    EpisodeDirectorOutput,
    StoryReviewOutput,
    StorySourceBriefOutput,
)
from src.pipeline.content.story_mapping.pair_adjudicator import PairDecisionBatch
from src.pipeline.content.story_mapping.cluster_reconciler import (
    ComponentReconciliationOutput,
)
from src.pipeline.content.story_mapping.event_identity import EventIdentityOutput
from src.pipeline.content.story_mapping.story_label import StoryLabelOutput


def _strict_schema_failures(schema: dict, path: str = "root") -> list[str]:
    failures: list[str] = []
    if schema.get("type") == "object":
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        if schema.get("additionalProperties") is not False:
            failures.append(f"{path}: additionalProperties")
        for field_name in sorted(set(properties) - required):
            failures.append(f"{path}.{field_name}: optional")
        for field_name, field_schema in properties.items():
            failures.extend(_strict_schema_failures(field_schema, f"{path}.{field_name}"))
    if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
        failures.extend(_strict_schema_failures(schema["items"], f"{path}[]"))
    for composition in ("anyOf", "oneOf", "allOf"):
        for index, item in enumerate(schema.get(composition, [])):
            if isinstance(item, dict):
                failures.extend(
                    _strict_schema_failures(item, f"{path}.{composition}[{index}]")
                )
    return failures


def test_all_active_llm_output_models_are_openai_strict_schema_compatible() -> None:
    models = (
        TriageBatchOutput,
        PairDecisionBatch,
        EventIdentityOutput,
        ComponentReconciliationOutput,
        StoryLabelOutput,
        CandidateScreenDraft,
        RoundupDuplicateAudit,
        RoundupSlateDraft,
        RoundupSlateReviewDraft,
        MetadataDraftOutput,
        StorySourceBriefOutput,
        EpisodeDirectorOutput,
        StoryReviewOutput,
        BookendReviewOutput,
    )

    for model in models:
        schema = convert_to_openai_tool(model, strict=True)["function"]["parameters"]
        assert _strict_schema_failures(schema) == [], model.__name__
