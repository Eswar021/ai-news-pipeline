"""Contracts for topic_research: the LLM output models (framer + synthesizer).

Everything is source-grounded — dossier items carry the URL they came from — so the
deep_dive writer inherits the same source-fidelity discipline the pipeline enforces
elsewhere. Models are lenient (extra="ignore") because the LLM uses json_mode.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


# ---- framer output: the research plan ----
class ResearchQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore")
    question: str
    focus: str = ""  # mechanism | numbers | history | skeptics | primary_source | impact | …


class ResearchQuestions(BaseModel):
    model_config = ConfigDict(extra="ignore")
    questions: list[ResearchQuestion] = Field(default_factory=list)


# ---- synthesizer output: the grounded dossier ----
class SourceRef(BaseModel):
    model_config = ConfigDict(extra="ignore")
    url: str
    title: str = ""


class Claim(BaseModel):
    model_config = ConfigDict(extra="ignore")
    claim: str
    evidence: str = ""
    source_url: str = ""


class Quote(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: str
    speaker: str = ""
    source_url: str = ""


class NumberFact(BaseModel):
    model_config = ConfigDict(extra="ignore")
    value: str  # the number with its unit, e.g. "$2,000", "10 problems"
    context: str = ""
    source_url: str = ""


class TimelineEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    date: str = ""
    event: str = ""


class Angle(BaseModel):
    model_config = ConfigDict(extra="ignore")
    angle: str
    why: str = ""


class Counterpoint(BaseModel):
    model_config = ConfigDict(extra="ignore")
    point: str
    source_url: str = ""


class ResearchDossier(BaseModel):
    model_config = ConfigDict(extra="ignore")
    topic: str = ""
    summary: str = ""
    claims: list[Claim] = Field(default_factory=list)
    quotes: list[Quote] = Field(default_factory=list)
    numbers: list[NumberFact] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    angles: list[Angle] = Field(default_factory=list)
    counterpoints: list[Counterpoint] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)

    def item_count(self) -> int:
        return sum(
            len(x)
            for x in (self.claims, self.quotes, self.numbers, self.timeline, self.angles, self.counterpoints)
        )


def empty_dossier(topic: str = "") -> dict:
    """A pass-through dossier for formats that don't research (e.g. roundup)."""
    return ResearchDossier(topic=topic).model_dump(mode="json")
