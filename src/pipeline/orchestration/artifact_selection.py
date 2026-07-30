from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.pipeline.contracts import (
    file_sha256,
    require_matching_run_id,
    require_parent_fingerprint,
    validate_artifact_provenance,
    validate_script_provenance,
    visual_plan_artifact_payload,
    voiceover_artifact_payload,
)


def fingerprint_token(fingerprint: str, length: int = 12) -> str:
    value = str(fingerprint or "").strip()
    if not value.startswith("sha256:"):
        raise ValueError("A sha256 fingerprint is required")
    return value.split(":", 1)[1][:length]


def resolve_script_result(
    *,
    run_dir: str | Path,
    run_id: str,
) -> tuple[Path, dict[str, Any]]:
    root = Path(run_dir)
    path = root / "script_generation" / "script_generation_result.json"
    if not path.exists():
        raise FileNotFoundError(f"No canonical script result exists: {path}")
    result = _load_json(path)
    if result.get("status") != "ok":
        raise ValueError(f"Selected script result is not ready: {path}")
    data = result.get("data") or {}
    require_matching_run_id(run_id, data.get("run_id"), "script_generation")
    validate_script_provenance(
        data.get("script_package") or {},
        run_id=run_id,
        upstream_run_id=data.get("run_id"),
    )
    return path, result


def resolve_voiceover_package(
    *,
    run_dir: str | Path,
    run_id: str,
    script_fingerprint: str,
    variant: str | Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    run_root = Path(run_dir).expanduser().resolve()
    root = run_root / "voiceover"
    if variant:
        requested = Path(variant)
        if not requested.is_absolute():
            requested = root / requested
        path = requested if requested.name == "voiceover_package.json" else requested / "voiceover_package.json"
        candidates = [path]
    else:
        candidates = sorted(root.glob("*/voiceover_package.json"))
    matches: list[tuple[Path, dict[str, Any]]] = []
    rejected: list[str] = []
    for path in candidates:
        if not path.exists():
            rejected.append(f"{path}: missing")
            continue
        package = _load_json(path)
        try:
            require_matching_run_id(run_id, package.get("run_id"), "voiceover")
            validate_artifact_provenance(
                package.get("provenance"),
                artifact_type="voiceover",
                run_id=run_id,
                payload=voiceover_artifact_payload(package),
                label="voiceover",
            )
            _validate_voiceover_audio_file(package, run_root=run_root)
            require_parent_fingerprint(
                package.get("provenance"),
                parent_name="script",
                expected=script_fingerprint,
                label="voiceover",
            )
        except ValueError as exc:
            rejected.append(f"{path}: {exc}")
            continue
        matches.append((path, package))
    if not matches:
        detail = f" Rejected: {'; '.join(rejected[:5])}" if rejected else ""
        raise FileNotFoundError(f"No voiceover package matches the selected script fingerprint.{detail}")
    if len(matches) > 1 and variant is None:
        choices = ", ".join(path.parent.name for path, _ in matches)
        raise ValueError(f"Multiple matching voiceovers exist ({choices}); set VOICEOVER_VARIANT explicitly")
    return matches[0]


def validate_visual_plan_result(
    result: dict[str, Any],
    *,
    run_id: str,
    script_fingerprint: str,
    voiceover_fingerprint: str,
) -> dict[str, Any]:
    if result.get("status") != "ok":
        raise ValueError(f"Visual scene plan is not ready: {result.get('summary', {})}")
    data = result.get("data") or {}
    require_matching_run_id(run_id, data.get("run_id"), "visual_scene_planning")
    plan = data.get("visual_scene_plan") or {}
    provenance = plan.get("provenance")
    validate_artifact_provenance(
        provenance,
        artifact_type="visual_plan",
        run_id=run_id,
        payload=visual_plan_artifact_payload(plan),
        label="visual_scene_plan",
    )
    require_parent_fingerprint(
        provenance,
        parent_name="script",
        expected=script_fingerprint,
        label="visual_scene_plan",
    )
    require_parent_fingerprint(
        provenance,
        parent_name="voiceover",
        expected=voiceover_fingerprint,
        label="visual_scene_plan",
    )
    return plan


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload


def _validate_voiceover_audio_file(package: dict[str, Any], *, run_root: Path) -> None:
    audio = package.get("audio") or {}
    path_value = str(audio.get("full_audio_path") or "").strip()
    if not path_value:
        raise ValueError("voiceover.audio.full_audio_path is required")
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = _project_root_from_run_dir(run_root) / path
    path = path.resolve()
    if not path.exists() or not path.is_file():
        raise ValueError(f"voiceover audio file does not exist: {path}")
    declared = str((package.get("provenance") or {}).get("audio_sha256") or "").strip()
    actual = file_sha256(path)
    if declared != actual:
        raise ValueError("voiceover WAV does not match provenance.audio_sha256")


def _project_root_from_run_dir(run_dir: Path) -> Path:
    for candidate in (run_dir, *run_dir.parents):
        if candidate.name == "output":
            return candidate.parent
    raise ValueError(f"run_dir must be inside the canonical output/ tree: {run_dir}")
