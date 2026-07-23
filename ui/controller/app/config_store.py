from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Callable

import yaml

from .storage import ControllerStore


class ConfigError(ValueError):
    pass


class ConfigConflict(ConfigError):
    pass


SECRET_KEY_RE = re.compile(
    r"(?i)(?:^|_)(?:api_key|access_token|password|passwd|secret|credential|cookie)s?$"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*(?::-[^}]*)?\}$")


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader: UniqueKeyLoader, node, deep: bool = False):
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConfigError(f"Duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


class ConfigStore:
    def __init__(
        self,
        project_root: Path,
        controller_store: ControllerStore,
        *,
        pipeline_python: str,
        validator: Callable[[Path], dict[str, Any]] | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.config_root = (self.project_root / "src" / "pipeline" / "config").resolve()
        self.controller_store = controller_store
        self.pipeline_python = pipeline_python
        self.validator = validator

    def files(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not self.config_root.exists():
            return rows
        for path in sorted(self.config_root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".yaml", ".yml"}:
                continue
            try:
                resolved = self._contain(path)
            except ConfigError:
                continue
            text = resolved.read_text(encoding="utf-8", errors="replace")
            rows.append({
                "path": resolved.relative_to(self.config_root).as_posix(),
                "size": resolved.stat().st_size,
                "sha256": self._sha(text),
                "modified_at": resolved.stat().st_mtime,
            })
        return rows

    def read(self, relative: str) -> dict[str, Any]:
        path = self._resolve_existing(relative)
        text = path.read_text(encoding="utf-8")
        return {
            "path": path.relative_to(self.config_root).as_posix(),
            "text": text,
            "sha256": self._sha(text),
            "size": len(text.encode("utf-8")),
            "modified_at": path.stat().st_mtime,
        }

    def update(
        self,
        *,
        relative: str,
        expected_sha256: str,
        text: str,
        change_summary: str,
        confirm_write: bool,
    ) -> dict[str, Any]:
        if not confirm_write:
            raise ConfigError("Confirm the authoring-config write before saving")
        path = self._resolve_existing(relative)
        before = path.read_text(encoding="utf-8")
        before_sha = self._sha(before)
        if before_sha != expected_sha256:
            raise ConfigConflict("The YAML changed after it was opened; reload before saving")
        parsed = self._parse(text)
        self._reject_inline_secrets(parsed)
        validation = self._validate_candidate(path, text)

        mode = path.stat().st_mode
        temporary = path.with_name(f".{path.name}.run-desk-{os.getpid()}.tmp")
        try:
            temporary.write_text(text, encoding="utf-8")
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

        after_sha = self._sha(text)
        revision_id = self.controller_store.save_config_revision(
            path=path.relative_to(self.config_root).as_posix(),
            before_sha256=before_sha,
            after_sha256=after_sha,
            before_text=before,
            after_text=text,
            change_summary=change_summary.strip(),
        )
        return {
            **self.read(relative),
            "revision_id": revision_id,
            "validation": validation,
        }

    def revisions(self, relative: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        normalized = None
        if relative:
            normalized = self._resolve_existing(relative).relative_to(self.config_root).as_posix()
        return self.controller_store.config_revisions(normalized, limit)

    def _parse(self, text: str) -> dict[str, Any]:
        try:
            value = yaml.load(text, Loader=UniqueKeyLoader)
        except (yaml.YAMLError, ConfigError) as exc:
            raise ConfigError(f"Invalid YAML: {exc}") from exc
        if not isinstance(value, dict):
            raise ConfigError("Authoring YAML must contain a mapping at the document root")
        return value

    def _reject_inline_secrets(self, value: Any, path: tuple[str, ...] = ()) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                next_path = path + (str(key),)
                normalized_key = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
                if SECRET_KEY_RE.search(normalized_key) and child is not None and child != "":
                    if not (isinstance(child, str) and PLACEHOLDER_RE.fullmatch(child.strip())):
                        raise ConfigError(
                            f"Credentials must remain in environment variables, not YAML: {'.'.join(next_path)}"
                        )
                self._reject_inline_secrets(child, next_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self._reject_inline_secrets(child, path + (str(index),))

    def _validate_candidate(self, path: Path, text: str) -> dict[str, Any]:
        self._assert_no_symlinks()
        with tempfile.TemporaryDirectory(prefix="run-desk-config-") as temp:
            temp_config = Path(temp) / "config"
            shutil.copytree(self.config_root, temp_config, symlinks=False)
            relative = path.relative_to(self.config_root)
            (temp_config / relative).write_text(text, encoding="utf-8")
            manifest = temp_config / "workbench.yaml"
            if self.validator:
                result = self.validator(manifest)
            else:
                command = [
                    self.pipeline_python,
                    "-m",
                    "ui.controller.app.config_probe",
                    "--manifest",
                    str(manifest),
                ]
                completed = subprocess.run(
                    command,
                    cwd=self.project_root,
                    capture_output=True,
                    text=True,
                    timeout=45,
                    check=False,
                )
                if completed.returncode != 0:
                    reason = (completed.stderr or completed.stdout or "Config validation failed").strip()
                    raise ConfigError(reason[-4000:])
                try:
                    result = yaml.safe_load(completed.stdout)
                except yaml.YAMLError as exc:
                    raise ConfigError(f"Config validator returned unreadable output: {exc}") from exc
            if not isinstance(result, dict) or result.get("status") != "ok":
                raise ConfigError(str((result or {}).get("error") or "Config composition failed"))
            return {
                "status": "ok",
                "profile_count": len(result.get("profiles") or []),
                "environment_count": len(result.get("environments") or []),
                "document_count": len(result.get("documents") or []),
            }

    def _assert_no_symlinks(self) -> None:
        for candidate in self.config_root.rglob("*"):
            if candidate.is_symlink():
                raise ConfigError(
                    f"Config validation refuses symlinks: {candidate.relative_to(self.config_root)}"
                )

    def _resolve_existing(self, relative: str) -> Path:
        candidate = Path(relative)
        if (
            not relative
            or candidate.is_absolute()
            or "\x00" in relative
            or any(part == ".." for part in candidate.parts)
            or candidate.suffix.lower() not in {".yaml", ".yml"}
        ):
            raise ConfigError("Only existing YAML beneath src/pipeline/config can be edited")
        path = self._contain(self.config_root / candidate)
        if not path.is_file():
            raise FileNotFoundError(relative)
        return path

    def _contain(self, path: Path) -> Path:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.config_root)
        except ValueError as exc:
            raise ConfigError("Config path escapes src/pipeline/config") from exc
        return resolved

    @staticmethod
    def _sha(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
