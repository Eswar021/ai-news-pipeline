"""Fold a grounded research dossier into the deep_dive story.

The deep_dive writer grounds every narration beat in a truth-index built from the
story's ``records`` — a fact it can't cite to a record is a hard validation error.
So web research can't be a loose side-payload: to be *usable*, its facts must enter
that same machinery. This module folds the dossier's grounded items
(claims/quotes/numbers/counterpoints, each carrying a real ``source_url``) into the
story as **synthetic source records**, one per source URL. Downstream, the source
researcher, truth index, and beat validation treat them exactly like article records
— fully citable, fully validated, no prompt conflict, no wasted research.

The dossier's *framing* (summary, suggested angles, timeline) has no per-source URL,
so it is returned separately as a non-citable ``research_brief`` for the director to
shape the angle sections with — never a source a writer grounds a fact in.

Pure: returns a new story dict (the input is not mutated) plus the research_brief.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from ...shared.utils import clean_text


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _http_url(value: str) -> str:
    value = clean_text(value)
    return value if value.startswith(("http://", "https://")) else ""


def _assemble_content(groups: dict[str, list[str]]) -> str:
    """Render one source's grounded items as labelled, readable text the source
    researcher can read exactly like an article body."""
    sections = (
        ("CLAIMS", groups["claims"]),
        ("DIRECT QUOTES", groups["quotes"]),
        ("KEY NUMBERS", groups["numbers"]),
        ("COUNTERPOINTS / SKEPTICISM", groups["counterpoints"]),
    )
    blocks: list[str] = []
    for label, lines in sections:
        if lines:
            body = "\n".join(f"- {line}" for line in lines)
            blocks.append(f"{label}:\n{body}")
    return "\n\n".join(blocks)


def build_research_brief(dossier: dict[str, Any]) -> dict[str, Any]:
    """The non-citable framing the director uses to choose/order angle sections."""
    summary = clean_text(dossier.get("summary"))
    angles = [
        {"angle": clean_text(a.get("angle")), "why": clean_text(a.get("why"))}
        for a in (dossier.get("angles") or [])
        if isinstance(a, dict) and clean_text(a.get("angle"))
    ]
    timeline = [
        {"date": clean_text(e.get("date")), "event": clean_text(e.get("event"))}
        for e in (dossier.get("timeline") or [])
        if isinstance(e, dict) and clean_text(e.get("event"))
    ]
    brief: dict[str, Any] = {}
    if summary:
        brief["topic_summary"] = summary
    if angles:
        brief["suggested_angles"] = angles
    if timeline:
        brief["timeline"] = timeline
    return brief


def merge_dossier_into_story(
    story: dict[str, Any], dossier: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (augmented_story, research_brief).

    Grounded dossier items become synthetic ``research_src_NN`` records keyed by
    source URL and appended to ``records`` (and to ``video_segment.source_record_keys``
    when that allow-list is present). Framing is returned as the research_brief.
    A dossier with no grounded items leaves the story unchanged.
    """
    if not isinstance(dossier, dict):
        return story, {}

    titles = {
        _http_url(s.get("url")): clean_text(s.get("title"))
        for s in (dossier.get("sources") or [])
        if isinstance(s, dict) and _http_url(s.get("url"))
    }

    # Group grounded items by the URL they cite; drop items without a real URL —
    # an ungrounded "fact" is exactly what this pipeline refuses to state.
    buckets: dict[str, dict[str, list[str]]] = {}

    def bucket(url: str) -> dict[str, list[str]]:
        return buckets.setdefault(
            url, {"claims": [], "quotes": [], "numbers": [], "counterpoints": []}
        )

    for c in dossier.get("claims") or []:
        url, claim = _http_url(c.get("source_url")), clean_text(c.get("claim"))
        if url and claim:
            evidence = clean_text(c.get("evidence"))
            bucket(url)["claims"].append(f"{claim} — {evidence}" if evidence else claim)
    for q in dossier.get("quotes") or []:
        url, text = _http_url(q.get("source_url")), clean_text(q.get("text"))
        if url and text:
            speaker = clean_text(q.get("speaker"))
            bucket(url)["quotes"].append(f'"{text}" — {speaker}' if speaker else f'"{text}"')
    for n in dossier.get("numbers") or []:
        url, value = _http_url(n.get("source_url")), clean_text(n.get("value"))
        if url and value:
            context = clean_text(n.get("context"))
            bucket(url)["numbers"].append(f"{value}: {context}" if context else value)
    for cp in dossier.get("counterpoints") or []:
        url, point = _http_url(cp.get("source_url")), clean_text(cp.get("point"))
        if url and point:
            bucket(url)["counterpoints"].append(point)

    research_brief = build_research_brief(dossier)
    if not buckets:
        return story, research_brief

    augmented = dict(story)
    records = [dict(r) for r in (story.get("records") or []) if isinstance(r, dict)]
    new_keys: list[str] = []
    for order, (url, groups) in enumerate(buckets.items(), start=1):
        content = _assemble_content(groups)
        if not content:
            continue
        key = f"research_src_{order:02d}"
        records.append(
            {
                "record_key": key,
                "title": titles.get(url) or f"Web research source {order}",
                "url": url,
                "content": content,
                "summary": content[:500],
                "source": _domain(url) or "web_research",
                "source_name": _domain(url) or "web research",
                "source_relationship": "web_research",
            }
        )
        new_keys.append(key)

    if not new_keys:
        return story, research_brief

    augmented["records"] = records
    # source_record_keys() prefers video_segment.source_record_keys when present, so
    # the synthetic keys must be added there too or they'd never be citable.
    video_segment = augmented.get("video_segment")
    if isinstance(video_segment, dict) and video_segment.get("source_record_keys"):
        vs = dict(video_segment)
        vs["source_record_keys"] = [*vs["source_record_keys"], *new_keys]
        augmented["video_segment"] = vs

    return augmented, research_brief


__all__ = ["merge_dossier_into_story", "build_research_brief"]
