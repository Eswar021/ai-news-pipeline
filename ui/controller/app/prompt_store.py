"""Editing for the pipeline's prompt files (the .txt system / user-preamble prompts
under src/pipeline/content/**/prompts/**).

Isolated from ConfigStore on purpose: the YAML config path stays untouched, and
prompts get their own store with the SAME safety guards (path containment, no
symlinks, sha conflict detection, revision history, secret rejection) minus the
YAML-only bits (mapping parse, full profile-composition validation). A prompt is
free text, so validation is: non-empty, size-capped, and no pasted credentials.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
from typing import Any

from .config_store import ConfigConflict, ConfigError
from .storage import ControllerStore

MAX_PROMPT_BYTES = 200_000
# Obvious API-key shapes, so a prompt can never smuggle a live credential into the repo.
SECRET_TOKEN_RE = re.compile(r"(sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_\-]{20,}|ghp_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})")


class PromptStore:
    """Read/edit/version the .txt prompt files, rooted at src/pipeline/content."""

    def __init__(self, project_root: Path, controller_store: ControllerStore) -> None:
        self.project_root = project_root.resolve()
        self.content_root = (self.project_root / "src" / "pipeline" / "content").resolve()
        self.controller_store = controller_store

    # --- listing / reading ---
    def files(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not self.content_root.exists():
            return rows
        for path in sorted(self.content_root.rglob("*.txt")):
            if not path.is_file() or "prompts" not in path.parts:
                continue
            try:
                resolved = self._contain(path)
            except ConfigError:
                continue
            rel = resolved.relative_to(self.content_root).as_posix()
            text = resolved.read_text(encoding="utf-8", errors="replace")
            rows.append({
                "path": rel,
                "kind": "prompt",
                "group": rel.split("/", 1)[0],          # owning module, e.g. script_generation
                "name": self._pretty_name(rel),
                "size": resolved.stat().st_size,
                "sha256": self._sha(text),
                "modified_at": resolved.stat().st_mtime,
            })
        return rows

    def read(self, relative: str) -> dict[str, Any]:
        path = self._resolve_existing(relative)
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(self.content_root).as_posix()
        return {
            "path": rel,
            "kind": "prompt",
            "group": rel.split("/", 1)[0],
            "name": self._pretty_name(rel),
            "text": text,
            "sha256": self._sha(text),
            "size": len(text.encode("utf-8")),
            "modified_at": path.stat().st_mtime,
        }

    # --- writing ---
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
            raise ConfigError("Confirm the prompt write before saving")
        path = self._resolve_existing(relative)
        if len(text.encode("utf-8")) > MAX_PROMPT_BYTES:
            raise ConfigError(f"Prompt exceeds the {MAX_PROMPT_BYTES:,}-byte limit")
        if not text.strip():
            raise ConfigError("A prompt cannot be empty")
        secret = SECRET_TOKEN_RE.search(text)
        if secret:
            raise ConfigError("Remove the credential-looking token before saving a prompt")
        before = path.read_text(encoding="utf-8")
        before_sha = self._sha(before)
        if before_sha != expected_sha256:
            raise ConfigConflict("The prompt changed after it was opened; reload before saving")

        mode = path.stat().st_mode
        temporary = path.with_name(f".{path.name}.run-desk-{os.getpid()}.tmp")
        try:
            temporary.write_text(text, encoding="utf-8")
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

        rel = path.relative_to(self.content_root).as_posix()
        revision_id = self.controller_store.save_config_revision(
            path=rel,
            before_sha256=before_sha,
            after_sha256=self._sha(text),
            before_text=before,
            after_text=text,
            change_summary=change_summary.strip(),
        )
        return {**self.read(relative), "revision_id": revision_id}

    def revisions(self, relative: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        normalized = None
        if relative:
            normalized = self._resolve_existing(relative).relative_to(self.content_root).as_posix()
        return self.controller_store.config_revisions(normalized, limit)

    # --- helpers (mirror ConfigStore's containment guards) ---
    @staticmethod
    def _pretty_name(rel: str) -> str:
        parts = rel.split("/")
        return "/".join(parts[-2:]) if len(parts) >= 2 else rel

    def _resolve_existing(self, relative: str) -> Path:
        candidate = Path(relative)
        if (
            not relative
            or candidate.is_absolute()
            or "\x00" in relative
            or any(part == ".." for part in candidate.parts)
            or candidate.suffix.lower() != ".txt"
            or "prompts" not in candidate.parts
        ):
            raise ConfigError("Only existing prompt .txt files beneath a prompts/ dir can be edited")
        path = self._contain(self.content_root / candidate)
        if path.is_symlink() or path.parent.is_symlink():
            raise ConfigError("Prompt editing refuses symlinks")
        if not path.is_file():
            raise FileNotFoundError(relative)
        return path

    def _contain(self, path: Path) -> Path:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.content_root)
        except ValueError as exc:
            raise ConfigError("Prompt path escapes src/pipeline/content") from exc
        return resolved

    @staticmethod
    def _sha(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
