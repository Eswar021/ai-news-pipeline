from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any


SCRIPT_CONTRACT_VERSION = "script_generation_result_v1"
PROVENANCE_CONTRACT_VERSION = "artifact_provenance_v1"
_WHITESPACE_RE = re.compile(r"\s+")


def artifact_fingerprint(payload: Any) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(serialized).hexdigest()}"


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def build_script_provenance(
    script_package: dict[str, Any],
    *,
    run_id: str,
    script_source: str | None = None,
) -> dict[str, Any]:
    canonical = _canonical_script_payload(script_package)
    fingerprint = artifact_fingerprint(canonical)
    return {
        "contract_version": SCRIPT_CONTRACT_VERSION,
        "provenance_version": PROVENANCE_CONTRACT_VERSION,
        "artifact_type": "script",
        "run_id": _required_text(run_id, "run_id"),
        "script_source": _clean_text(
            script_source
            or script_package.get("script_source")
            or script_package.get("generation_source")
            or "unknown"
        ),
        "script_fingerprint": fingerprint,
        "artifact_fingerprint": fingerprint,
        "section_count": len(canonical["sections"]),
        "beat_count": sum(len(section["beats"]) for section in canonical["sections"]),
    }


def build_text_script_provenance(
    script_text: str,
    *,
    run_id: str,
    script_source: str,
) -> dict[str, Any]:
    text = _required_text(script_text, "script_text")
    fingerprint = artifact_fingerprint(
        {
            "contract_version": "manual_script_text_v1",
            "full_script": _clean_text(text),
        }
    )
    return {
        "contract_version": "manual_script_text_v1",
        "provenance_version": PROVENANCE_CONTRACT_VERSION,
        "artifact_type": "script",
        "run_id": _required_text(run_id, "run_id"),
        "script_source": _required_text(script_source, "script_source"),
        "script_fingerprint": fingerprint,
        "artifact_fingerprint": fingerprint,
        "section_count": 0,
        "beat_count": 0,
    }


def validate_script_provenance(
    script_package: dict[str, Any],
    *,
    run_id: str,
    upstream_run_id: str | None = None,
) -> dict[str, Any]:
    require_matching_run_id(run_id, upstream_run_id, "script_generation")
    declared = script_package.get("provenance")
    if not isinstance(declared, dict):
        raise ValueError("script_package.provenance is required; regenerate the canonical script with the current pipeline")
    declared_run_id = _required_text(declared.get("run_id"), "script_package.provenance.run_id")
    require_matching_run_id(run_id, declared_run_id, "script_package.provenance")
    expected = build_script_provenance(
        script_package,
        run_id=run_id,
        script_source=_clean_text(declared.get("script_source")),
    )
    declared_fingerprint = _required_text(
        declared.get("script_fingerprint"),
        "script_package.provenance.script_fingerprint",
    )
    if declared_fingerprint != expected["script_fingerprint"]:
        raise ValueError(
            "script_package provenance does not match its current sections/beats; regenerate downstream artifacts"
        )
    return {**declared, **expected}


def build_artifact_provenance(
    *,
    artifact_type: str,
    run_id: str,
    payload: Any,
    parents: dict[str, str],
    script_source: str = "",
) -> dict[str, Any]:
    cleaned_parents = {
        _required_text(name, "parent name"): _required_fingerprint(value, f"parent_fingerprints.{name}")
        for name, value in sorted(parents.items())
    }
    fingerprint = artifact_fingerprint(
        {
            "artifact_type": _required_text(artifact_type, "artifact_type"),
            "parents": cleaned_parents,
            "payload": payload,
        }
    )
    provenance = {
        "provenance_version": PROVENANCE_CONTRACT_VERSION,
        "artifact_type": artifact_type,
        "run_id": _required_text(run_id, "run_id"),
        "artifact_fingerprint": fingerprint,
        "parent_fingerprints": cleaned_parents,
    }
    if cleaned_parents.get("script"):
        provenance["script_fingerprint"] = cleaned_parents["script"]
    if cleaned_parents.get("voiceover"):
        provenance["voiceover_fingerprint"] = cleaned_parents["voiceover"]
    if cleaned_parents.get("visual_plan"):
        provenance["visual_plan_fingerprint"] = cleaned_parents["visual_plan"]
    if script_source:
        provenance["script_source"] = _clean_text(script_source)
    if artifact_type == "voiceover":
        provenance["voiceover_fingerprint"] = fingerprint
    elif artifact_type == "visual_plan":
        provenance["visual_plan_fingerprint"] = fingerprint
    return provenance


def require_matching_run_id(expected: str, actual: str | None, label: str) -> None:
    expected_value = _required_text(expected, "run.run_id")
    actual_value = _required_text(actual, f"{label}.run_id")
    if actual_value != expected_value:
        raise ValueError(f"{label}.run_id {actual_value!r} does not match run.run_id {expected_value!r}")


def require_parent_fingerprint(
    provenance: dict[str, Any] | None,
    *,
    parent_name: str,
    expected: str,
    label: str,
) -> None:
    if not isinstance(provenance, dict):
        raise ValueError(f"{label}.provenance is required")
    actual = (provenance.get("parent_fingerprints") or {}).get(parent_name)
    if not actual and parent_name == "script":
        actual = provenance.get("script_fingerprint")
    if not actual and parent_name == "voiceover":
        actual = provenance.get("voiceover_fingerprint")
    if not actual and parent_name == "visual_plan":
        actual = provenance.get("visual_plan_fingerprint")
    expected_value = _required_fingerprint(expected, f"expected {parent_name} fingerprint")
    actual_value = _required_fingerprint(actual, f"{label} {parent_name} fingerprint")
    if actual_value != expected_value:
        raise ValueError(
            f"{label} was produced from a different {parent_name}: {actual_value} != {expected_value}"
        )


def validate_artifact_provenance(
    provenance: dict[str, Any] | None,
    *,
    artifact_type: str,
    run_id: str,
    payload: Any,
    label: str,
) -> dict[str, Any]:
    if not isinstance(provenance, dict):
        raise ValueError(f"{label}.provenance is required")
    require_matching_run_id(run_id, provenance.get("run_id"), f"{label}.provenance")
    if _clean_text(provenance.get("artifact_type")) != artifact_type:
        raise ValueError(f"{label}.provenance.artifact_type must be {artifact_type!r}")
    parents = provenance.get("parent_fingerprints")
    if not isinstance(parents, dict) or not parents:
        raise ValueError(f"{label}.provenance.parent_fingerprints is required")
    expected = build_artifact_provenance(
        artifact_type=artifact_type,
        run_id=run_id,
        parents=parents,
        script_source=_clean_text(provenance.get("script_source")),
        payload=payload,
    )
    declared = _required_fingerprint(
        provenance.get("artifact_fingerprint"),
        f"{label}.provenance.artifact_fingerprint",
    )
    if declared != expected["artifact_fingerprint"]:
        raise ValueError(f"{label} contents do not match its artifact fingerprint")
    return {**provenance, **expected}


def visual_plan_artifact_payload(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "planning_strategy": plan.get("planning_strategy", ""),
        "episode_style": plan.get("episode_style", {}),
        "story_sections": plan.get("story_sections", []),
        "scene_timeline": plan.get("scene_timeline", []),
    }


def voiceover_artifact_payload(package: dict[str, Any]) -> dict[str, Any]:
    audio = package.get("audio") if isinstance(package.get("audio"), dict) else {}
    return {
        "provider": package.get("provider", ""),
        "voice": package.get("voice", ""),
        "style": package.get("style", {}),
        "sample_rate_hz": audio.get("sample_rate_hz", 0),
        "duration_seconds": audio.get("duration_seconds", 0),
        "audio_sha256": (package.get("provenance") or {}).get("audio_sha256", ""),
        "audio_units": [_identity_audio_unit(unit) for unit in package.get("audio_units", [])],
    }


def final_video_artifact_payload(package: dict[str, Any]) -> dict[str, Any]:
    return {
        "scene_ids": package.get("scene_ids", []),
        "final_video_sha256": package.get("final_video_sha256", ""),
        "audio_encoding": package.get("audio_encoding", {}),
    }


def _identity_audio_unit(unit: dict[str, Any]) -> dict[str, Any]:
    return {
        "audio_unit_id": unit.get("audio_unit_id", ""),
        "unit_order": unit.get("unit_order", 0),
        "section_id": unit.get("section_id", ""),
        "story_id": unit.get("story_id", ""),
        "start_seconds": unit.get("start_seconds", 0),
        "end_seconds": unit.get("end_seconds", 0),
        "aligned_beats": [
            {
                "beat_id": beat.get("beat_id", ""),
                "beat_order": beat.get("beat_order", 0),
                "text": beat.get("text", ""),
                "start_seconds": beat.get("start_seconds", 0),
                "end_seconds": beat.get("end_seconds", 0),
            }
            for beat in unit.get("aligned_beats", [])
            if isinstance(beat, dict)
        ],
    }


def _canonical_script_payload(script_package: dict[str, Any]) -> dict[str, Any]:
    sections = script_package.get("sections")
    if not isinstance(sections, list):
        raise ValueError("script_package.sections must be a list before provenance can be created")
    canonical_sections: list[dict[str, Any]] = []
    for section in sorted(
        (item for item in sections if isinstance(item, dict)),
        key=lambda item: (_safe_int(item.get("section_order"), 0), _clean_text(item.get("section_id"))),
    ):
        beats = section.get("beats")
        if not isinstance(beats, list):
            raise ValueError(f"{section.get('section_id', '<unknown>')} beats must be a list")
        canonical_beats = [
            {
                "beat_id": _required_text(beat.get("beat_id"), "beat_id"),
                "beat_order": _safe_int(beat.get("beat_order"), 0),
                "beat_type": _clean_text(beat.get("beat_type")),
                "story_id": _clean_text(beat.get("story_id")),
                "narration_text": _required_text(beat.get("narration_text"), "beat narration_text"),
            }
            for beat in sorted(
                (item for item in beats if isinstance(item, dict)),
                key=lambda item: (_safe_int(item.get("beat_order"), 0), _clean_text(item.get("beat_id"))),
            )
        ]
        canonical_sections.append(
            {
                "section_id": _required_text(section.get("section_id"), "section_id"),
                "section_order": _safe_int(section.get("section_order"), 0),
                "section_type": _clean_text(section.get("section_type")),
                "story_id": _clean_text(section.get("story_id")),
                "beats": canonical_beats,
            }
        )
    return {
        "contract_version": SCRIPT_CONTRACT_VERSION,
        "package_type": _clean_text(script_package.get("package_type")),
        "selected_format": _clean_text(script_package.get("selected_format")),
        "sections": canonical_sections,
    }


def _clean_text(value: Any) -> str:
    return _WHITESPACE_RE.sub(" ", str(value or "")).strip()


def _required_text(value: Any, label: str) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        raise ValueError(f"{label} must not be empty")
    return cleaned


def _required_fingerprint(value: Any, label: str) -> str:
    cleaned = _required_text(value, label)
    if not cleaned.startswith("sha256:") or len(cleaned) != 71:
        raise ValueError(f"{label} must be a sha256 fingerprint")
    return cleaned


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
