"""topic_research: research the selected topic on the web, then synthesize a
grounded dossier the deep_dive writer uses instead of one article's records.

Flow: frame (LLM → questions) → search (Tavily per question) → synthesize (LLM →
dossier). Format-gated: non-research formats (roundup) get an instant pass-through.
Reuses the script_generation shared LLM plumbing (runtimes + structured invoke).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..script_generation.shared.invocation import invoke_runtime_chain
from ..script_generation.shared.runtimes import build_llm_runtimes
from ..script_generation.shared.utils import clean_text, json_dumps, story_id, story_title
from .contract import ResearchDossier, ResearchQuestions, empty_dossier
from .prompt_loader import load_prompt_bundle
from .search_client import SearchError, search

RESEARCH_LLM_ROLES = ("framer", "synthesizer")


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _passthrough(run_id: str, generated_at: str, selected_format: str, *, reason: str, llm_calls=None) -> dict:
    """Deep_dive still works without research (falls back to the story's records);
    roundup never researches. Either way we return a valid, empty dossier."""
    return {
        "status": "ok",
        "data": {
            "run_id": run_id,
            "generated_at": generated_at,
            "selected_format": selected_format,
            "researched": False,
            "research_dossier": empty_dossier(),
            "source_count": 0,
        },
        "summary": {"researched": False, "reason": reason, "llm_call_count": len(llm_calls or [])},
        "handoff": {"ready_for_script_generation": True},
    }


def _topic_brief(story: dict[str, Any]) -> dict[str, Any]:
    identity = story.get("story_identity") if isinstance(story.get("story_identity"), dict) else {}
    records = []
    for record in (story.get("records") or [])[:4]:
        records.append(
            {
                "title": clean_text(record.get("title")),
                "url": clean_text(record.get("url")),
                "excerpt": clean_text(record.get("content") or record.get("summary"))[:1200],
            }
        )
    return {
        "story_id": story_id(story),
        "title": story_title(story),
        "one_sentence": clean_text(identity.get("one_sentence_story")),
        "primary_entity": clean_text(identity.get("primary_entity")),
        "known_records": records,
    }


def _gather_sources(questions, config: dict[str, Any], search_cfg: dict[str, Any], logger=None) -> list[dict[str, Any]]:
    provider = clean_text(search_cfg.get("provider")) or "tavily"
    per_q = int(search_cfg.get("max_results_per_question", 4))
    max_sources = int(search_cfg.get("max_sources", 12))
    depth = clean_text(search_cfg.get("search_depth")) or "advanced"
    timeout = float(search_cfg.get("request_timeout_seconds", 30))

    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for q in questions:
        if len(sources) >= max_sources:
            break
        query = clean_text(getattr(q, "question", "") or (q.get("question") if isinstance(q, dict) else ""))
        if not query:
            continue
        try:
            results = search(query, provider=provider, max_results=per_q, search_depth=depth, timeout=timeout)
        except SearchError as exc:
            if logger:
                logger.logger.warning("topic_research search skipped for %r: %s", query[:60], exc)
            continue
        for r in results:
            url = clean_text(r.get("url"))
            if not url or url in seen:
                continue
            seen.add(url)
            sources.append({"title": clean_text(r.get("title")), "url": url, "content": clean_text(r.get("content"))})
            if len(sources) >= max_sources:
                break
    return sources


def run(input_json: dict) -> dict:
    run_req = input_json.get("run") if isinstance(input_json.get("run"), dict) else {}
    config = input_json.get("config") if isinstance(input_json.get("config"), dict) else {}
    inp = input_json.get("input") if isinstance(input_json.get("input"), dict) else {}
    run_id = clean_text(run_req.get("run_id"))
    generated_at = _iso_now()

    vp_data = ((inp.get("video_packaging") or {}).get("data")) or {}
    selected_format = clean_text(vp_data.get("selected_format"))
    packet = vp_data.get("video_packet") or {}
    llm_calls: list[dict[str, Any]] = []

    enabled_formats = set(config.get("enabled_formats") or ["deep_dive"])
    if not bool(config.get("enabled", True)) or selected_format not in enabled_formats:
        return _passthrough(run_id, generated_at, selected_format, reason=f"research not enabled for format {selected_format!r}")

    stories = packet.get("stories") or []
    if not stories:
        return _passthrough(run_id, generated_at, selected_format, reason="no story to research")
    topic = _topic_brief(stories[0])

    try:
        runtimes = build_llm_runtimes(config, RESEARCH_LLM_ROLES)
        search_cfg = config.get("search") or {}

        # 1. Frame the research.
        framer = invoke_runtime_chain(
            module_name="topic_research_framer",
            output_model=ResearchQuestions,
            llm_runtime=runtimes["framer"],
            prompt_bundle=load_prompt_bundle("topic_research_framer", config["prompt_version"]),
            task_payload=json_dumps({"topic": topic, "max_questions": int(search_cfg.get("max_questions", 6))}),
            metadata={"story_id": topic["story_id"]},
            llm_calls=llm_calls,
        )
        questions = list(framer.questions)[: int(search_cfg.get("max_questions", 6))]

        # 2. Search the web.
        sources = _gather_sources(questions, config, search_cfg)
        if not sources:
            return _passthrough(run_id, generated_at, selected_format, reason="no web sources resolved", llm_calls=llm_calls)

        # 3. Synthesize the grounded dossier.
        dossier_model = invoke_runtime_chain(
            module_name="topic_research_synthesizer",
            output_model=ResearchDossier,
            llm_runtime=runtimes["synthesizer"],
            prompt_bundle=load_prompt_bundle("topic_research_synthesizer", config["prompt_version"]),
            task_payload=json_dumps({"topic": topic, "sources": sources}),
            metadata={"story_id": topic["story_id"], "source_count": len(sources)},
            llm_calls=llm_calls,
        )
        dossier = dossier_model.model_dump(mode="json")
    except Exception as exc:
        # Research is an enhancement — never let it break a deep_dive run. Degrade
        # to the pass-through; the writer falls back to the story's own records.
        return _passthrough(
            run_id, generated_at, selected_format,
            reason=f"research failed, degraded to records: {type(exc).__name__}: {exc}",
            llm_calls=llm_calls,
        )

    return {
        "status": "ok",
        "data": {
            "run_id": run_id,
            "generated_at": generated_at,
            "selected_format": selected_format,
            "researched": True,
            "research_dossier": dossier,
            "source_count": len(sources),
        },
        "summary": {
            "researched": True,
            "question_count": len(questions),
            "source_count": len(sources),
            "dossier_item_count": dossier_model.item_count(),
            "llm_call_count": len(llm_calls),
        },
        "handoff": {"ready_for_script_generation": True},
        "llm_calls": llm_calls,
    }
