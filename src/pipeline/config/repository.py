from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


SCHEMA_VERSION = "pipeline_modular_config_v1"


@dataclass(frozen=True)
class ConfigDocument:
    value: dict[str, Any]
    sha256: str
    source_paths: tuple[str, ...]

    def snapshot(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "source_paths": list(self.source_paths),
            "config": deepcopy(self.value),
        }


class ConfigRepository:
    """Resolve profile and module authoring config without leaking YAML into apps."""

    def __init__(self, manifest_path: Path) -> None:
        self.manifest_path = manifest_path.expanduser().resolve()
        self.config_root = self.manifest_path.parent
        self._manifest = self._load_yaml(self.manifest_path)

    @property
    def default_profile(self) -> str:
        value = str(self._manifest.get("default_run_profile") or "").strip()
        if not value:
            raise KeyError("workbench config is missing default_run_profile")
        return value

    @property
    def schema_version(self) -> str:
        return str(self._manifest.get("config_schema_version") or "legacy_inline_profile")

    def profile_names(self) -> tuple[str, ...]:
        profiles = self._profiles()
        return tuple(str(name) for name in profiles)

    def profile(self, profile_name: str) -> ConfigDocument:
        spec = self._profile_spec(profile_name)
        if not self._is_modular(spec):
            return self._document(deepcopy(spec), [self.manifest_path])

        shared_path = self._resolve_config_path(spec.get("profile_file"), "profile_file")
        shared = self._load_yaml(shared_path)
        value = deepcopy(shared)
        sources = [self.manifest_path, shared_path]
        stages = spec.get("stages")
        if not isinstance(stages, dict) or not stages:
            raise ValueError(f"Modular profile {profile_name!r} has no stages")
        for stage_name, modules in stages.items():
            if not isinstance(modules, dict):
                raise TypeError(f"Profile stage {stage_name!r} must map module names to YAML paths")
            if stage_name == "visuals":
                stage_value: dict[str, Any] = {}
                for module_name, relative_path in modules.items():
                    path = self._resolve_config_path(relative_path, f"{stage_name}.{module_name}")
                    stage_value[str(module_name)] = self._load_yaml(path)
                    sources.append(path)
                value["visuals"] = stage_value
                continue
            for module_name, relative_path in modules.items():
                path = self._resolve_config_path(relative_path, f"{stage_name}.{module_name}")
                value[str(module_name)] = self._load_yaml(path)
                sources.append(path)
        return self._document(value, sources)

    def shared(self, profile_name: str) -> ConfigDocument:
        spec = self._profile_spec(profile_name)
        if not self._is_modular(spec):
            shared = {
                key: deepcopy(value)
                for key, value in spec.items()
                if key in {"channel", "orchestration"}
            }
            return self._document(shared, [self.manifest_path])
        path = self._resolve_config_path(spec.get("profile_file"), "profile_file")
        return self._document(self._load_yaml(path), [self.manifest_path, path])

    def module(self, profile_name: str, stage: str, module: str) -> ConfigDocument:
        spec = self._profile_spec(profile_name)
        if not self._is_modular(spec):
            if stage == "visuals":
                stage_config = spec.get("visuals")
                value = stage_config.get(module) if isinstance(stage_config, dict) else None
            else:
                value = spec.get(module)
            if not isinstance(value, dict) or not value:
                raise KeyError(f"Profile {profile_name!r} is missing config for {stage}.{module}")
            return self._document(deepcopy(value), [self.manifest_path])

        stages = spec.get("stages")
        modules = stages.get(stage) if isinstance(stages, dict) else None
        relative_path = modules.get(module) if isinstance(modules, dict) else None
        path = self._resolve_config_path(relative_path, f"{stage}.{module}")
        return self._document(self._load_yaml(path), [self.manifest_path, path])

    def experiment(self, experiment_name: str) -> ConfigDocument:
        experiments = self._manifest.get("experiments")
        value = experiments.get(experiment_name) if isinstance(experiments, dict) else None
        if not isinstance(value, dict):
            raise KeyError(f"Unknown experiment config: {experiment_name}")
        return self._document(deepcopy(value), [self.manifest_path])

    def _profiles(self) -> dict[str, Any]:
        profiles = self._manifest.get("profiles")
        if not isinstance(profiles, dict) or not profiles:
            raise ValueError("workbench config must contain at least one profile")
        return profiles

    def _profile_spec(self, profile_name: str) -> dict[str, Any]:
        value = self._profiles().get(profile_name)
        if not isinstance(value, dict):
            raise KeyError(f"Unknown run profile: {profile_name}")
        return value

    @staticmethod
    def _is_modular(spec: dict[str, Any]) -> bool:
        return bool(spec.get("profile_file") or spec.get("stages"))

    def _resolve_config_path(self, value: Any, label: str) -> Path:
        relative = str(value or "").strip()
        if not relative:
            raise KeyError(f"Modular config is missing path for {label}")
        path = (self.config_root / relative).resolve()
        try:
            path.relative_to(self.config_root)
        except ValueError as exc:
            raise ValueError(f"Config path for {label} escapes config root: {path}") from exc
        if not path.is_file():
            raise FileNotFoundError(f"Config file for {label} not found: {path}")
        return path

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"Expected YAML object at {path}")
        return value

    def _document(self, value: dict[str, Any], sources: list[Path]) -> ConfigDocument:
        unique_sources = tuple(dict.fromkeys(path.resolve() for path in sources))
        identity = {
            "schema_version": self.schema_version,
            "sources": [
                {
                    "path": str(path.relative_to(self.config_root)),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for path in unique_sources
            ],
            "value": value,
        }
        digest = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()
        return ConfigDocument(
            value=deepcopy(value),
            sha256=digest,
            source_paths=tuple(str(path.relative_to(self.config_root)) for path in unique_sources),
        )
