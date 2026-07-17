from __future__ import annotations

import base64
import json
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, ConfigDict, Field

from ..common import clean_text, normalize_text_list
from .llm_logging import build_llm_call_log


class VideoClipSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id: str
    visual_match: Literal["strong", "acceptable", "weak", "mismatch"]
    recommended_action: Literal["use", "reject"]
    confidence: float = Field(ge=0, le=1)
    reason: str


def select_video_clip_start(
    *,
    candidate: dict[str, Any],
    scene: dict[str, Any],
    clip_duration: float,
    config: dict[str, Any],
    llm,
    system_prompt: str,
    llm_calls: list[dict[str, Any]],
    ffmpeg_path: str,
    timeout_seconds: int,
    user_agent: str,
    work_dir: Path,
) -> dict[str, Any]:
    total_duration = float(candidate.get("duration_seconds", 0.0) or 0.0)
    max_start = max(0.0, total_duration - clip_duration)
    if max_start <= 0.25:
        return {
            "status": "whole_clip",
            "start_seconds": 0.0,
            "sample_id": "whole_clip",
            "confidence": 1.0,
            "reason": "The candidate is no longer than the requested clip window.",
        }

    sample_starts = sample_start_seconds(
        max_start=max_start,
        count=int(config["max_video_sample_frames"]),
    )
    sample_dir = work_dir / f".{clean_text(candidate.get('candidate_id'))}_clip_samples"
    sample_dir.mkdir(parents=True, exist_ok=True)
    samples: list[dict[str, Any]] = []
    try:
        for index, start_seconds in enumerate(sample_starts, start=1):
            frame_seconds = min(
                max(0.0, total_duration - 0.1),
                start_seconds + min(clip_duration / 2, 2.0),
            )
            frame_path = sample_dir / f"sample_{index:02d}.jpg"
            try:
                _extract_frame(
                    video_url=clean_text(candidate.get("download_url")),
                    frame_seconds=frame_seconds,
                    output_path=frame_path,
                    ffmpeg_path=ffmpeg_path,
                    timeout_seconds=timeout_seconds,
                    user_agent=user_agent,
                )
            except Exception:
                continue
            samples.append(
                {
                    "sample_id": f"sample_{index:02d}",
                    "start_seconds": round(start_seconds, 3),
                    "frame_seconds": round(frame_seconds, 3),
                    "frame_path": frame_path,
                }
            )
        if len(samples) < 2:
            raise ValueError("fewer than two video frames could be sampled")

        selection = _select_sample(
            scene=scene,
            candidate=candidate,
            samples=samples,
            config=config,
            llm=llm,
            system_prompt=system_prompt,
            llm_calls=llm_calls,
        )
        selected = next(
            (sample for sample in samples if sample["sample_id"] == selection["sample_id"]),
            None,
        )
        if selected is None:
            raise ValueError(f"clip selector returned unknown sample_id {selection['sample_id']!r}")
        if not clip_selection_passes(selection):
            raise ValueError(
                "the semantic clip selector rejected every sampled window: "
                f"{selection['reason']}"
            )
        return {
            "status": "verified",
            "start_seconds": selected["start_seconds"],
            "sample_id": selected["sample_id"],
            "frame_seconds": selected["frame_seconds"],
            "confidence": selection["confidence"],
            "visual_match": selection["visual_match"],
            "reason": selection["reason"],
            "sample_count": len(samples),
        }
    finally:
        shutil.rmtree(sample_dir, ignore_errors=True)


def sample_start_seconds(*, max_start: float, count: int) -> list[float]:
    if max_start <= 0 or count <= 1:
        return [0.0]
    step = max_start / (count - 1)
    return [round(step * index, 3) for index in range(count)]


def clip_selection_passes(selection: dict[str, Any]) -> bool:
    return selection.get("recommended_action") == "use"


def _select_sample(
    *,
    scene: dict[str, Any],
    candidate: dict[str, Any],
    samples: list[dict[str, Any]],
    config: dict[str, Any],
    llm,
    system_prompt: str,
    llm_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    prompt_summary = _prompt_summary(scene, candidate, samples)
    chain = RunnableLambda(
        lambda inputs: _messages(
            system_prompt,
            scene,
            candidate,
            samples,
            retry_context=inputs,
        )
    ) | llm.with_structured_output(VideoClipSelection, include_raw=True)
    last_error = ""
    for attempt in range(1, int(config["max_attempts"]) + 1):
        started = time.time()
        raw = None
        parsed_output = None
        try:
            result = chain.invoke({"attempt": attempt, "previous_error": last_error})
            raw = result.get("raw") if isinstance(result, dict) else None
            parsed = result.get("parsed") if isinstance(result, dict) else result
            parsing_error = result.get("parsing_error") if isinstance(result, dict) else None
            if parsing_error is not None or parsed is None:
                raise ValueError(f"structured output parsing failed: {parsing_error}")
            output = parsed if isinstance(parsed, VideoClipSelection) else VideoClipSelection.model_validate(parsed)
            parsed_output = output.model_dump(mode="json")
            if parsed_output["sample_id"] not in {sample["sample_id"] for sample in samples}:
                raise ValueError(f"unknown sample_id {parsed_output['sample_id']!r}")
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            llm_calls.append(
                build_llm_call_log(
                    model=config["model"],
                    prompt_summary=prompt_summary,
                    raw_response=raw,
                    parsed_output=parsed_output,
                    metadata={
                        "scene_id": clean_text(scene.get("scene_id")),
                        "candidate_id": clean_text(candidate.get("candidate_id")),
                        "attempt": attempt,
                    },
                    duration_seconds=time.time() - started,
                    parse_error=last_error,
                    module_name="video_clip_selector",
                )
            )
            continue
        llm_calls.append(
            build_llm_call_log(
                model=config["model"],
                prompt_summary=prompt_summary,
                raw_response=raw,
                parsed_output=parsed_output,
                metadata={
                    "scene_id": clean_text(scene.get("scene_id")),
                    "candidate_id": clean_text(candidate.get("candidate_id")),
                    "attempt": attempt,
                },
                duration_seconds=time.time() - started,
                module_name="video_clip_selector",
            )
        )
        return parsed_output
    raise RuntimeError(f"video clip selector failed after bounded retries: {last_error}")


def _messages(
    system_prompt: str,
    scene: dict[str, Any],
    candidate: dict[str, Any],
    samples: list[dict[str, Any]],
    *,
    retry_context: dict[str, Any],
) -> list:
    task_payload = _task_payload(scene, candidate, samples)
    if clean_text(retry_context.get("previous_error")):
        task_payload["repair_context"] = {
            "attempt": retry_context.get("attempt"),
            "previous_error": clean_text(retry_context.get("previous_error")),
            "instruction": "Return one valid supplied sample_id.",
        }
    content: list[dict[str, Any]] = [
        {"type": "text", "text": json.dumps(task_payload, ensure_ascii=False, indent=2)}
    ]
    for sample in samples:
        content.extend(
            [
                {
                    "type": "text",
                    "text": (
                        f"{sample['sample_id']} at {sample['frame_seconds']:.3f}s "
                        f"(clip starts at {sample['start_seconds']:.3f}s)"
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": _data_url(sample["frame_path"]), "detail": "low"},
                },
            ]
        )
    return [SystemMessage(content=system_prompt), HumanMessage(content=content)]


def _task_payload(
    scene: dict[str, Any],
    candidate: dict[str, Any],
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
    return {
        "task": "Select the best sampled moment for this exact narration scene.",
        "scene": {
            "scene_id": clean_text(scene.get("scene_id")),
            "story_title": clean_text(scene.get("story_title")),
            "script_excerpt": clean_text(scene.get("script_excerpt")),
            "visual_intent": clean_text(scene.get("visual_intent")),
            "must_show": normalize_text_list(payload.get("must_show")),
            "must_avoid": normalize_text_list(payload.get("must_avoid")),
        },
        "candidate": {
            "candidate_id": clean_text(candidate.get("candidate_id")),
            "title": clean_text(candidate.get("title")),
            "description": clean_text(candidate.get("description")),
            "tags": candidate.get("tags", []),
        },
        "samples": [
            {
                "sample_id": sample["sample_id"],
                "clip_start_seconds": sample["start_seconds"],
                "frame_seconds": sample["frame_seconds"],
            }
            for sample in samples
        ],
        "required_sample_ids": [sample["sample_id"] for sample in samples],
    }


def _prompt_summary(
    scene: dict[str, Any],
    candidate: dict[str, Any],
    samples: list[dict[str, Any]],
) -> str:
    return json.dumps(_task_payload(scene, candidate, samples), ensure_ascii=False)


def _extract_frame(
    *,
    video_url: str,
    frame_seconds: float,
    output_path: Path,
    ffmpeg_path: str,
    timeout_seconds: int,
    user_agent: str,
) -> None:
    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{frame_seconds:.3f}",
        "-user_agent",
        user_agent,
        "-i",
        video_url,
        "-frames:v",
        "1",
        "-vf",
        "scale=640:-2:force_original_aspect_ratio=decrease",
        "-q:v",
        "3",
        str(output_path),
    ]
    subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise ValueError("ffmpeg did not extract a usable sample frame")


def _data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"
