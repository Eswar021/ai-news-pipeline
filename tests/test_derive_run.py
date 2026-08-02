"""Derived runs: reuse a base run's Phase-1 corpus for a different format.

The lineage check compares manifest YAML paths (drift-proof), so these tests need
only a base run dir with a completed shared corpus, not captured config snapshots.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.pipeline.orchestration.content_phases import SHARED_CORPUS_MODULES
from src.pipeline.orchestration.derive import (
    DeriveError,
    create_derived_run_context,
    derivable_target_profiles,
    incompatible_shared_modules,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKBENCH = REPO_ROOT / "src" / "pipeline" / "config" / "workbench.yaml"
BASE_PROFILE = "daily_48h_all_sources"
TARGET_PROFILE = "daily_deep_dive"


def _seed_base_run(output_root: Path, *, run_id: str, complete: bool = True) -> Path:
    run_dir = output_root / "runs" / run_id
    for module in SHARED_CORPUS_MODULES:
        module_dir = run_dir / module
        module_dir.mkdir(parents=True, exist_ok=True)
        (module_dir / f"{module}_input.json").write_text("{}", encoding="utf-8")
        if module != "editorial_selection" or complete:
            (module_dir / f"{module}_result.json").write_text(
                json.dumps({"status": "ok"}), encoding="utf-8"
            )
    (run_dir / "inputs").mkdir(exist_ok=True)
    (run_dir / "inputs" / "seed.json").write_text("{}", encoding="utf-8")
    # A stray Phase-2 dir + orchestration state that must NOT be carried over.
    (run_dir / "video_packaging").mkdir(exist_ok=True)
    (run_dir / "video_packaging" / "video_packaging_result.json").write_text("{}", encoding="utf-8")
    (run_dir / "orchestration").mkdir(exist_ok=True)
    (run_dir / "orchestration" / "run_state.json").write_text(
        json.dumps({"run_id": run_id}), encoding="utf-8"
    )
    context = {
        "schema_version": "pipeline_run_context_v1",
        "run_id": run_id,
        "created_at": "2026-08-02T00:00:00+05:30",
        "run_profile": BASE_PROFILE,
        "config_environment": "prod",
        "run_dir": str(run_dir),
        "output_root": str(output_root),
    }
    (run_dir / "run_context.json").write_text(json.dumps(context), encoding="utf-8")
    return run_dir


def test_incompatible_shared_modules_uses_manifest_paths() -> None:
    manifest = {
        "profiles": {
            "base": {"stages": {
                "ingestion": {"news_collection": "a/news.yaml"},
                "content": {
                    "evidence_prep": "a/ev.yaml",
                    "editorial_triage": "a/tri.yaml",
                    "story_mapping": "a/map.yaml",
                    "editorial_selection": "a/sel.yaml",
                },
            }},
            "sibling": {"stages": {  # same Phase-1 paths => compatible
                "ingestion": {"news_collection": "a/news.yaml"},
                "content": {
                    "evidence_prep": "a/ev.yaml",
                    "editorial_triage": "a/tri.yaml",
                    "story_mapping": "a/map.yaml",
                    "editorial_selection": "a/sel.yaml",
                },
            }},
            "stranger": {"stages": {  # different selection => incompatible on that module
                "ingestion": {"news_collection": "a/news.yaml"},
                "content": {
                    "evidence_prep": "a/ev.yaml",
                    "editorial_triage": "a/tri.yaml",
                    "story_mapping": "a/map.yaml",
                    "editorial_selection": "b/other_sel.yaml",
                },
            }},
        }
    }
    assert incompatible_shared_modules(manifest=manifest, base_profile="base", target_profile="sibling") == []
    assert incompatible_shared_modules(manifest=manifest, base_profile="base", target_profile="stranger") == [
        "editorial_selection"
    ]


def test_derive_materializes_a_new_run_from_the_shared_corpus(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    _seed_base_run(output_root, run_id="run_base_daily_48h_all_sources")

    derived = create_derived_run_context(
        project_root=REPO_ROOT,
        base_run_id="run_base_daily_48h_all_sources",
        target_profile=TARGET_PROFILE,
        config_path=WORKBENCH,
        output_root=output_root,
    )

    assert derived["run_profile"] == TARGET_PROFILE
    assert derived["derived_from"] == "run_base_daily_48h_all_sources"
    assert derived["derived_shared_corpus"] == list(SHARED_CORPUS_MODULES)
    # target profile snapshot, not the base's roundup one
    assert derived["profile_config"]["video_packaging"]["target_format"] == "deep_dive"

    derived_dir = Path(derived["run_dir"])
    for module in SHARED_CORPUS_MODULES:
        assert (derived_dir / module / f"{module}_result.json").is_file(), module
    assert (derived_dir / "inputs" / "seed.json").is_file()
    # Phase-2 artifacts and stale state are NOT carried over.
    assert not (derived_dir / "video_packaging").exists()
    assert not (derived_dir / "orchestration").exists()


def test_derive_rejects_incomplete_corpus(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    _seed_base_run(output_root, run_id="run_partial_daily_48h_all_sources", complete=False)
    with pytest.raises(DeriveError, match="editorial_selection"):
        create_derived_run_context(
            project_root=REPO_ROOT,
            base_run_id="run_partial_daily_48h_all_sources",
            target_profile=TARGET_PROFILE,
            config_path=WORKBENCH,
            output_root=output_root,
        )


def test_derive_rejects_unknown_profile(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    _seed_base_run(output_root, run_id="run_base2_daily_48h_all_sources")
    with pytest.raises(DeriveError, match="Unknown target profile"):
        create_derived_run_context(
            project_root=REPO_ROOT,
            base_run_id="run_base2_daily_48h_all_sources",
            target_profile="no_such_profile",
            config_path=WORKBENCH,
            output_root=output_root,
        )


def test_derivable_target_profiles_includes_deep_dive(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    _seed_base_run(output_root, run_id="run_base3_daily_48h_all_sources")
    targets = derivable_target_profiles(
        project_root=REPO_ROOT,
        base_run_id="run_base3_daily_48h_all_sources",
        config_path=WORKBENCH,
        output_root=output_root,
    )
    assert TARGET_PROFILE in targets
    # a run with no completed corpus yields no targets
    _seed_base_run(output_root, run_id="run_empty_daily_48h_all_sources", complete=False)
    assert derivable_target_profiles(
        project_root=REPO_ROOT,
        base_run_id="run_empty_daily_48h_all_sources",
        config_path=WORKBENCH,
        output_root=output_root,
    ) == []
