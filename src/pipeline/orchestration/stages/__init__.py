from typing import Any


def run_content_stage(input_json: dict[str, Any]) -> dict[str, Any]:
    from .content import run

    return run(input_json)


def run_voiceover_stage(input_json: dict[str, Any]) -> dict[str, Any]:
    from .voiceover import run

    return run(input_json)


def run_visuals_stage(input_json: dict[str, Any]) -> dict[str, Any]:
    from .visuals import run

    return run(input_json)

__all__ = ["run_content_stage", "run_voiceover_stage", "run_visuals_stage"]
