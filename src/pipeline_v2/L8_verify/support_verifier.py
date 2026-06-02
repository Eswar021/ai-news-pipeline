from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
from string import Template

from src.llm.client import OpenAIJSONClient
from src.pipeline.L1_collection.common import clean_text


ALLOWED_SUPPORT_STATUSES = {
    "directly_supported",
    "supported_with_caution",
    "analysis_supported",
    "overclaim",
    "unsupported",
    "verification_error",
    "not_verified",
    "no_verification_needed",
}
ALLOWED_SEVERITIES = {"info", "warning", "medium", "high"}


def verify_sentence_support(
    sentence_map: list[dict],
    script_package: dict,
    *,
    layer8_cfg: dict,
    prompt_bundle: dict,
    log_path: Path,
) -> list[dict]:
    story_sections = _story_sections_to_verify(sentence_map)
    worker_count = int(layer8_cfg["verifier_worker_count"])
    if worker_count < 1:
        raise ValueError("layer_8.verifier_worker_count must be at least 1")

    print(f"[L8] Support-verifier workers: {worker_count}")

    verified_by_sentence_id = {}
    if worker_count == 1:
        for section_id, sentences in story_sections.items():
            for result in _verify_section(
                section_id,
                sentences,
                script_package,
                layer8_cfg=layer8_cfg,
                prompt_bundle=prompt_bundle,
                log_path=log_path,
            ):
                verified_by_sentence_id[result["sentence_id"]] = result
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_section = {
                executor.submit(
                    _verify_section,
                    section_id,
                    sentences,
                    script_package,
                    layer8_cfg=layer8_cfg,
                    prompt_bundle=prompt_bundle,
                    log_path=log_path,
                ): section_id
                for section_id, sentences in story_sections.items()
            }
            for future in as_completed(future_to_section):
                section_id = future_to_section[future]
                results = future.result()
                for result in results:
                    verified_by_sentence_id[result["sentence_id"]] = result
                issue_count = sum(1 for result in results if result["support_status"] in {"overclaim", "unsupported"})
                print(f"[L8] Support verified — {section_id} issues={issue_count}")

    final = []
    for sentence in sentence_map:
        sentence_id = sentence["sentence_id"]
        if sentence_id in verified_by_sentence_id:
            final.append({**sentence, **verified_by_sentence_id[sentence_id]})
        elif not sentence.get("requires_support_verification"):
            status = "analysis_supported" if sentence.get("is_analysis_sentence") else "no_verification_needed"
            final.append(
                {
                    **sentence,
                    "support_status": status,
                    "severity": "info",
                    "issue": None,
                    "recommended_fix": None,
                }
            )
        else:
            final.append(
                {
                    **sentence,
                    "support_status": "not_verified",
                    "severity": "warning",
                    "issue": "Support verifier did not return a result for this sentence.",
                    "recommended_fix": "Rerun L8 support verification for this section.",
                }
            )
    return final


def _verify_section(
    section_id: str,
    sentences: list[dict],
    script_package: dict,
    *,
    layer8_cfg: dict,
    prompt_bundle: dict,
    log_path: Path,
) -> list[dict]:
    client = OpenAIJSONClient(model=layer8_cfg["support_verifier_model"])
    remaining_sentences = list(sentences)
    collected_by_sentence_id: dict[str, dict] = {}
    try:
        for attempt in range(1, 4):
            user_prompt = _build_user_prompt(section_id, remaining_sentences, script_package, prompt_bundle)
            response = client.generate_json(
                module_name="sentence_support_verifier",
                system_prompt=prompt_bundle["system"],
                user_prompt=user_prompt,
                log_path=log_path,
                metadata={
                    "section_id": section_id,
                    "sentence_count": len(sentences),
                    "remaining_sentence_count": len(remaining_sentences),
                    "attempt": attempt,
                },
            )
            results = _validate_response(response, section_id, remaining_sentences)
            for result in results:
                collected_by_sentence_id[result["sentence_id"]] = result
            remaining_sentences = [
                sentence
                for sentence in sentences
                if sentence["sentence_id"] not in collected_by_sentence_id
            ]
            if not remaining_sentences:
                return list(collected_by_sentence_id.values())
        return list(collected_by_sentence_id.values())
    except Exception as exc:
        return [
            {
                "sentence_id": sentence["sentence_id"],
                "section_id": section_id,
                "support_status": "verification_error",
                "severity": "warning",
                "issue": f"Support verifier error: {str(exc)[:160]}",
                "recommended_fix": "Rerun L8 after checking LLM availability.",
            }
            for sentence in sentences
        ]


def _build_user_prompt(section_id: str, sentences: list[dict], script_package: dict, prompt_bundle: dict) -> str:
    section = _section_by_id(script_package, section_id)
    fact_index = script_package.get("evidence_usage", {}).get("fact_index", {})
    fact_ids = _dedupe(
        fact_id
        for sentence in sentences
        for fact_id in sentence.get("used_fact_ids", [])
    )
    fact_ids = _dedupe(
        list(section.get("available_fact_ids", []))
        + list(section.get("required_fact_ids", []))
        + list(section.get("used_fact_ids", []))
        + fact_ids
    )
    facts = [_compact_fact(fact_index[fact_id]) for fact_id in fact_ids if fact_id in fact_index]
    payload = {
        "section_key": section_id,
        "section_title": section.get("title", ""),
        "section_type": section.get("section_type", ""),
        "required_cautious_fact_ids": section.get("required_cautious_fact_ids", []),
        "facts_available_to_verify_against": facts,
        "sentences_to_verify": [
            {
                "sentence_id": sentence["sentence_id"],
                "sentence_text": sentence["sentence_text"],
                "used_fact_ids": sentence.get("used_fact_ids", []),
                "is_analysis_sentence": sentence.get("is_analysis_sentence", False),
            }
            for sentence in sentences
        ],
    }
    preamble = Template(prompt_bundle.get("user_preamble", "")).safe_substitute(section_key=section_id)
    return (
        "Verify whether each spoken sentence is supported by the carried-forward facts and support snippets.\n"
        "Use only the facts in this payload. Do not bring in outside knowledge.\n\n"
        f"Verification payload:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        f"{preamble}"
    )


def _compact_fact(fact: dict) -> dict:
    support_records = []
    for support in fact.get("support_records", [])[:4]:
        support_records.append(
            {
                "record_key": support.get("record_key", ""),
                "source_name": support.get("source_name", ""),
                "source_url": support.get("source_url", ""),
                "source_group": support.get("source_group", ""),
                "support_level": support.get("support_level", ""),
                "matched_snippet": clean_text(support.get("matched_snippet", ""))[:900],
            }
        )
    return {
        "fact_id": fact.get("fact_id", ""),
        "fact_text": fact.get("fact_text", ""),
        "fact_type": fact.get("fact_type", ""),
        "status": fact.get("status", ""),
        "confidence": fact.get("confidence", ""),
        "support_records": support_records,
    }


def _validate_response(response: dict, section_id: str, sentences: list[dict]) -> list[dict]:
    raw = response.get("sentence_verifications", [])
    if not isinstance(raw, list):
        raise ValueError("sentence_support_verifier response missing sentence_verifications list")

    sentence_ids = {sentence["sentence_id"] for sentence in sentences}
    sentence_id_aliases = _sentence_id_aliases(sentences)
    cleaned = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        sentence_id = clean_text(item.get("sentence_id", ""))
        sentence_id = sentence_id_aliases.get(sentence_id, sentence_id)
        if sentence_id not in sentence_ids:
            continue
        status = clean_text(item.get("support_status", ""))
        if status not in ALLOWED_SUPPORT_STATUSES:
            status = "verification_error"
        severity = clean_text(item.get("severity", ""))
        if severity not in ALLOWED_SEVERITIES:
            severity = _severity_for_status(status)
        cleaned.append(
            {
                "sentence_id": sentence_id,
                "section_id": section_id,
                "support_status": status,
                "severity": severity,
                "issue": clean_text(item.get("issue", "")) or None,
                "recommended_fix": clean_text(item.get("recommended_fix", "")) or None,
            }
        )
    return cleaned


def _sentence_id_aliases(sentences: list[dict]) -> dict[str, str]:
    aliases = {}
    for sentence in sentences:
        sentence_id = sentence["sentence_id"]
        aliases[sentence_id] = sentence_id
        suffix = sentence_id.rsplit("_", 2)
        if len(suffix) == 3 and suffix[-2] == "sent":
            aliases[f"sent_{suffix[-1]}"] = sentence_id
            aliases[suffix[-1]] = sentence_id
        sentence_index = sentence.get("sentence_index")
        if sentence_index:
            index_text = f"{int(sentence_index):03d}"
            aliases[f"sent_{index_text}"] = sentence_id
            aliases[index_text] = sentence_id
    return aliases


def _story_sections_to_verify(sentence_map: list[dict]) -> dict[str, list[dict]]:
    sections: dict[str, list[dict]] = {}
    for sentence in sentence_map:
        if not sentence.get("requires_support_verification"):
            continue
        sections.setdefault(sentence["section_id"], []).append(sentence)
    return sections


def _section_by_id(script_package: dict, section_id: str) -> dict:
    for section in script_package.get("section_scripts", []):
        if section.get("section_id") == section_id:
            return section
    raise KeyError(f"Section not found in script package: {section_id}")


def _severity_for_status(status: str) -> str:
    if status == "unsupported":
        return "high"
    if status == "overclaim":
        return "medium"
    if status in {"verification_error", "not_verified"}:
        return "warning"
    return "info"


def _dedupe(values) -> list[str]:
    seen = set()
    kept = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        kept.append(value)
    return kept
