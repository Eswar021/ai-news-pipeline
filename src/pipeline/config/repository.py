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

    def __init__(self, manifest_path: Path, *, environment: str | None = None) -> None:
        self.manifest_path = manifest_path.expanduser().resolve()
        self.config_root = self.manifest_path.parent
        self._manifest = self._load_yaml(self.manifest_path)
        self.environment = (environment or self.default_environment).strip().lower()
        if not self.environment:
            raise ValueError("config environment must not be empty")
        self._environment_path, self._environment = self._load_environment(self.environment)

    @property
    def default_profile(self) -> str:
        value = str(self._manifest.get("default_run_profile") or "").strip()
        if not value:
            raise KeyError("workbench config is missing default_run_profile")
        return value

    @property
    def schema_version(self) -> str:
        return str(self._manifest.get("config_schema_version") or "legacy_inline_profile")

    @property
    def default_environment(self) -> str:
        return str(self._manifest.get("default_environment") or "prod").strip().lower()

    def environment_names(self) -> tuple[str, ...]:
        environments = self._manifest.get("environments")
        if not isinstance(environments, dict):
            return (self.default_environment,)
        return tuple(str(name) for name in environments)

    def profile_names(self) -> tuple[str, ...]:
        profiles = self._profiles()
        return tuple(str(name) for name in profiles)

    def profile(self, profile_name: str) -> ConfigDocument:
        spec = self._profile_spec(profile_name)
        if not self._is_modular(spec):
            value = self._apply_profile_environment(deepcopy(spec))
            return self._document(value, self._base_sources())

        shared_path = self._resolve_config_path(spec.get("profile_file"), "profile_file")
        shared = self._load_yaml(shared_path)
        value = self._merge(shared, self._environment_shared())
        sources = [self.manifest_path, *self._environment_sources(), shared_path]
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
                    stage_value[str(module_name)] = self._merge(
                        self._load_yaml(path),
                        self._environment_module(str(stage_name), str(module_name)),
                    )
                    sources.append(path)
                value["visuals"] = stage_value
                continue
            for module_name, relative_path in modules.items():
                path = self._resolve_config_path(relative_path, f"{stage_name}.{module_name}")
                value[str(module_name)] = self._merge(
                    self._load_yaml(path),
                    self._environment_module(str(stage_name), str(module_name)),
                )
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
            return self._document(
                self._merge(shared, self._environment_shared()),
                self._base_sources(),
            )
        path = self._resolve_config_path(spec.get("profile_file"), "profile_file")
        return self._document(
            self._merge(self._load_yaml(path), self._environment_shared()),
            [self.manifest_path, *self._environment_sources(), path],
        )

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
            return self._document(
                self._merge(value, self._environment_module(stage, module)),
                self._base_sources(),
            )

        stages = spec.get("stages")
        modules = stages.get(stage) if isinstance(stages, dict) else None
        relative_path = modules.get(module) if isinstance(modules, dict) else None
        path = self._resolve_config_path(relative_path, f"{stage}.{module}")
        return self._document(
            self._merge(self._load_yaml(path), self._environment_module(stage, module)),
            [self.manifest_path, *self._environment_sources(), path],
        )

    def experiment(self, experiment_name: str) -> ConfigDocument:
        experiments = self._manifest.get("experiments")
        value = experiments.get(experiment_name) if isinstance(experiments, dict) else None
        if isinstance(value, str):
            path = self._resolve_config_path(value, f"experiments.{experiment_name}")
            return self._document(self._load_yaml(path), [self.manifest_path, path])
        if not isinstance(value, dict):
            raise KeyError(f"Unknown experiment config: {experiment_name}")
        return self._document(deepcopy(value), [self.manifest_path])

    def _load_environment(self, environment: str) -> tuple[Path | None, dict[str, Any]]:
        environments = self._manifest.get("environments")
        if not isinstance(environments, dict):
            if environment != self.default_environment:
                raise KeyError(
                    f"Unknown config environment {environment!r}; manifest has no environment overlays"
                )
            return None, {}
        relative_path = environments.get(environment)
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise KeyError(
                f"Unknown config environment {environment!r}; expected one of {sorted(environments)}"
            )
        path = self._resolve_config_path(relative_path, f"environments.{environment}")
        overlay = self._load_yaml(path)
        unknown = set(overlay) - {"config_environment_schema_version", "shared", "modules"}
        if unknown:
            raise ValueError(
                f"Environment overlay {environment!r} contains unsupported keys: {sorted(unknown)}"
            )
        for key in ("shared", "modules"):
            value = overlay.get(key, {})
            if not isinstance(value, dict):
                raise TypeError(f"Environment overlay {environment!r}.{key} must be a mapping")
        return path, overlay

    def _environment_sources(self) -> list[Path]:
        return [self._environment_path] if self._environment_path is not None else []

    def _base_sources(self) -> list[Path]:
        return [self.manifest_path, *self._environment_sources()]

    def _environment_shared(self) -> dict[str, Any]:
        value = self._environment.get("shared", {})
        return deepcopy(value) if isinstance(value, dict) else {}

    def _environment_module(self, stage: str, module: str) -> dict[str, Any]:
        modules = self._environment.get("modules", {})
        stage_modules = modules.get(stage) if isinstance(modules, dict) else None
        value = stage_modules.get(module) if isinstance(stage_modules, dict) else None
        return deepcopy(value) if isinstance(value, dict) else {}

    def _apply_profile_environment(self, profile: dict[str, Any]) -> dict[str, Any]:
        value = self._merge(profile, self._environment_shared())
        modules = self._environment.get("modules", {})
        if not isinstance(modules, dict):
            return value
        for stage, stage_modules in modules.items():
            if not isinstance(stage_modules, dict):
                continue
            for module, overlay in stage_modules.items():
                if not isinstance(overlay, dict):
                    continue
                if stage == "visuals":
                    visual_config = value.setdefault("visuals", {})
                    current = visual_config.get(module, {}) if isinstance(visual_config, dict) else {}
                    visual_config[module] = self._merge(current, overlay)
                elif module in value:
                    value[module] = self._merge(value[module], overlay)
        return value

    @classmethod
    def _merge(cls, base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(base)
        for key, value in overlay.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = cls._merge(merged[key], value)
            else:
                merged[key] = deepcopy(value)
        return merged

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
