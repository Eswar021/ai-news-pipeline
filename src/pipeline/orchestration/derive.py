"""Derive a new run from an existing one: reuse the Phase-1 shared corpus and
materialize a fresh run tagged with a different profile, ready for Phase-2
(video_packaging onward).

This is the first-class version of the manual "copy the run dir, prune Phase-2,
patch run_context, delete stale state" dance. It lives in its own module because
the corpus-compatibility check reuses helpers from stages.common, which imports
run_context — importing them from run_context would be a cycle.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from .content_phases import (
    PHASE2_ENTRY_MODULE,
    SHARED_CORPUS_MODULE_STAGE,
    SHARED_CORPUS_MODULES,
    SHARED_CORPUS_TERMINAL_MODULE,
)
from .run_context import _write_json, create_run_context, load_run_context


class DeriveError(ValueError):
    """A derive request cannot be satisfied (bad base run or incompatible profile)."""


def _manifest(config_file: Path) -> dict[str, Any]:
    value = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DeriveError(f"Workbench manifest is not a mapping: {config_file}")
    return value


def _shared_corpus_paths(manifest: dict[str, Any], profile: str) -> dict[str, str | None]:
    """The YAML path each shared-corpus module resolves to for a profile. Two
    profiles share a corpus lineage iff these paths are equal — a declarative,
    drift-proof signal (unlike runtime config shas, which change as configs are
    edited even though the reused artifacts on disk do not)."""
    stages = ((manifest.get("profiles") or {}).get(profile) or {}).get("stages") or {}
    return {
        module: ((stages.get(SHARED_CORPUS_MODULE_STAGE[module]) or {}).get(module))
        for module in SHARED_CORPUS_MODULES
    }


def _can_run_phase2(manifest: dict[str, Any], profile: str) -> bool:
    content = (((manifest.get("profiles") or {}).get(profile) or {}).get("stages") or {}).get("content") or {}
    return bool(content.get(PHASE2_ENTRY_MODULE))


def incompatible_shared_modules(
    *,
    manifest: dict[str, Any],
    base_profile: str,
    target_profile: str,
) -> list[str]:
    """Shared-corpus modules whose target-profile YAML path differs from the base
    profile's. Empty list means the two profiles run the same Phase-1 pipeline, so
    the base corpus is safe to reuse for the target format."""
    base_paths = _shared_corpus_paths(manifest, base_profile)
    target_paths = _shared_corpus_paths(manifest, target_profile)
    return [
        module
        for module in SHARED_CORPUS_MODULES
        if not target_paths.get(module) or target_paths[module] != base_paths.get(module)
    ]


def derivable_target_profiles(
    *,
    project_root: Path,
    base_run_id: str,
    config_path: Path | None = None,
    output_root: Path | None = None,
) -> list[str]:
    """Every profile that can be derived to from this base run: it shares the base
    profile's Phase-1 lineage and can run Phase-2. Drives the UI target picker."""
    root = project_root.resolve()
    output = (output_root or root / "output").resolve()
    config_file = (config_path or root / "src" / "pipeline" / "config" / "workbench.yaml").resolve()
    base = load_run_context(output_root=output, run_id=base_run_id)
    if not _corpus_complete(Path(base["run_dir"])):
        return []
    base_profile = str(base.get("run_profile") or "")
    manifest = _manifest(config_file)
    return [
        profile
        for profile in (manifest.get("profiles") or {})
        if _can_run_phase2(manifest, profile)
        and not incompatible_shared_modules(
            manifest=manifest, base_profile=base_profile, target_profile=profile
        )
    ]


def create_derived_run_context(
    *,
    project_root: Path,
    base_run_id: str,
    target_profile: str,
    config_path: Path | None = None,
    output_root: Path | None = None,
    environment: str | None = None,
    requested_run_id: str | None = None,
    trigger: str = "derive",
    orchestrator: str = "",
) -> dict[str, Any]:
    root = project_root.resolve()
    output = (output_root or root / "output").resolve()
    config_file = (config_path or root / "src" / "pipeline" / "config" / "workbench.yaml").resolve()

    base = load_run_context(output_root=output, run_id=base_run_id)
    base_dir = Path(base["run_dir"])
    env = environment or str(base.get("config_environment") or "prod")

    if not _corpus_complete(base_dir):
        raise DeriveError(
            f"Base run {base_run_id!r} has not completed {SHARED_CORPUS_TERMINAL_MODULE}; "
            "only runs with a finished shared corpus can be derived from."
        )

    manifest = _manifest(config_file)
    if target_profile not in (manifest.get("profiles") or {}):
        raise DeriveError(f"Unknown target profile: {target_profile!r}")
    if not _can_run_phase2(manifest, target_profile):
        raise DeriveError(
            f"Target profile {target_profile!r} has no {PHASE2_ENTRY_MODULE} stage; it cannot run Phase-2."
        )

    base_profile = str(base.get("run_profile") or "")
    incompatible = incompatible_shared_modules(
        manifest=manifest, base_profile=base_profile, target_profile=target_profile
    )
    if incompatible:
        raise DeriveError(
            f"Target profile {target_profile!r} does not share base run {base_run_id!r}'s "
            f"Phase-1 lineage; differing shared stages: {', '.join(incompatible)}. "
            "A derived run reuses the base corpus, so both profiles must point these "
            "stages at the same config."
        )

    derived = create_run_context(
        project_root=root,
        run_profile=target_profile,
        run_id=(requested_run_id or None),
        trigger=trigger,
        orchestrator=orchestrator,
        config_path=config_file,
        output_root=output,
        config_environment=env,
    )
    derived_dir = Path(derived["run_dir"])
    if derived_dir.resolve() == base_dir.resolve():
        raise DeriveError("A derived run must not target the base run's directory.")

    # Seed the shared corpus + collect inputs. Leave orchestration/ absent so
    # RunStateStore builds fresh state under the new run id (copying the base's
    # run_state.json would fail the run_id-mismatch guard).
    for module in SHARED_CORPUS_MODULES:
        source = base_dir / module
        if source.is_dir():
            shutil.copytree(source, derived_dir / module, dirs_exist_ok=True)
    base_inputs = base_dir / "inputs"
    if base_inputs.is_dir():
        shutil.copytree(base_inputs, derived_dir / "inputs", dirs_exist_ok=True)

    derived["derived_from"] = base_run_id
    derived["derived_shared_corpus"] = list(SHARED_CORPUS_MODULES)
    _write_json(derived_dir / "run_context.json", derived)
    _write_json(output / "current_run.json", derived)
    return derived


def _corpus_complete(base_run_dir: Path) -> bool:
    terminal = (
        base_run_dir
        / SHARED_CORPUS_TERMINAL_MODULE
        / f"{SHARED_CORPUS_TERMINAL_MODULE}_result.json"
    )
    return terminal.is_file()


def run(input_json: dict[str, Any]) -> dict[str, Any]:
    """Runner stage wrapper: materialize a derived run from a base run."""
    run_req = input_json.get("run") if isinstance(input_json.get("run"), dict) else {}
    paths = input_json.get("paths") if isinstance(input_json.get("paths"), dict) else {}
    config = input_json.get("config") if isinstance(input_json.get("config"), dict) else {}

    base_run_id = str(config.get("base_run_id") or "").strip()
    target_profile = str(run_req.get("run_profile") or "").strip()
    if not base_run_id:
        raise DeriveError("derive requires config.base_run_id (the run to reuse the corpus from)")
    if not target_profile:
        raise DeriveError("derive requires run.run_profile (the target format profile)")

    project_root = Path(str(paths.get("project_root") or "."))
    output_root = Path(str(paths.get("output_root"))) if paths.get("output_root") else None
    config_path = Path(str(paths.get("pipeline_config_path"))) if paths.get("pipeline_config_path") else None

    derived = create_derived_run_context(
        project_root=project_root,
        base_run_id=base_run_id,
        target_profile=target_profile,
        config_path=config_path,
        output_root=output_root,
        environment=run_req.get("config_environment"),
        requested_run_id=(run_req.get("run_id") or None),
        orchestrator="src.pipeline.orchestration.runner:derive",
    )
    return {
        "status": "ok",
        "data": {
            "run_id": derived["run_id"],
            "run_profile": derived["run_profile"],
            "config_environment": derived.get("config_environment"),
            "run_dir": derived["run_dir"],
            "derived_from": derived["derived_from"],
            "stage": "derive",
        },
        "summary": {
            "base_run_id": base_run_id,
            "seeded_modules": list(SHARED_CORPUS_MODULES),
            "phase2_entry_module": PHASE2_ENTRY_MODULE,
        },
        "handoff": {"ready_for_content": True},
    }
