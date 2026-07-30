from __future__ import annotations

import difflib
import json
import mimetypes
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .catalog import MODULE_CATALOG, MODULE_PATHS, STAGE_CATALOG, STAGE_MODULES

DENIED_PARTS = {
    ".env",
    ".cache",
    "secrets",
    "secret",
    "credentials",
    "credential",
    "cookies",
    "cookie",
    "__pycache__",
}
DENIED_SUBSTRINGS = ("api_key", "apikey", "token", "password", "passwd", "credential", "cookie")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
ABSOLUTE_PATH_RE = re.compile(r"(?<![A-Za-z0-9_])/(?:Users|Volumes|private|tmp|var|etc|home)/[^\\s\"'<>),]+")
TEXT_EXTENSIONS = {".json", ".jsonl", ".txt", ".log", ".md", ".yaml", ".yml", ".srt", ".vtt", ".html"}
MEDIA_EXTENSIONS = {".wav", ".mp4", ".jpg", ".jpeg", ".png", ".webp", ".svg"}


class RepositoryError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedPath:
    root_name: str
    root: Path
    path: Path
    rel: str


def project_root_from_env() -> Path:
    env_root = os.getenv("RUN_INSPECTOR_PROJECT_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    return Path(__file__).resolve().parents[3]


class SafeRepository:
    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = (project_root or project_root_from_env()).resolve()
        self.output_root = (self.project_root / "output").resolve()
        self.runs_root = (self.output_root / "runs").resolve()
        self.config_root = (self.project_root / "src" / "pipeline" / "config").resolve()
        self.allowed_roots = {
            "output": self.output_root,
            "config": self.config_root,
        }

    def _ensure_not_denied(self, rel: str) -> None:
        path = Path(rel)
        lower_parts = [part.lower() for part in path.parts]
        if any(part in DENIED_PARTS for part in lower_parts):
            raise RepositoryError("Path is not allowed")
        filename = path.name.lower()
        if any(fragment in filename for fragment in DENIED_SUBSTRINGS):
            raise RepositoryError("Path is not allowed")

    def _validate_relative(self, rel: str) -> Path:
        if not rel or "\x00" in rel:
            raise RepositoryError("Missing path")
        candidate = Path(rel)
        if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
            raise RepositoryError("Path traversal is not allowed")
        self._ensure_not_denied(rel)
        return candidate

    def _contain(self, root_name: str, root: Path, candidate: Path) -> ResolvedPath:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise RepositoryError("Path escapes the allowed root") from exc
        rel = resolved.relative_to(root).as_posix()
        self._ensure_not_denied(rel)
        return ResolvedPath(root_name=root_name, root=root, path=resolved, rel=rel)

    def resolve_output_relative(self, rel: str) -> ResolvedPath:
        candidate = self._validate_relative(rel)
        if candidate.parts and candidate.parts[0] == "output":
            candidate = Path(*candidate.parts[1:])
        return self._contain("output", self.output_root, self.output_root / candidate)

    def resolve_config_relative(self, rel: str) -> ResolvedPath:
        candidate = self._validate_relative(rel)
        parts = candidate.parts
        prefix = ("src", "pipeline", "config")
        if len(parts) >= 3 and parts[:3] == prefix:
            candidate = Path(*parts[3:]) if len(parts) > 3 else Path(".")
        return self._contain("config", self.config_root, self.config_root / candidate)

    def resolve_allowlisted(self, rel: str) -> ResolvedPath:
        candidate = self._validate_relative(rel)
        parts = candidate.parts
        if parts and parts[0] == "output":
            return self.resolve_output_relative(rel)
        if len(parts) >= 3 and parts[:3] == ("src", "pipeline", "config"):
            return self.resolve_config_relative(rel)
        raise RepositoryError("Path must be beneath output/ or src/pipeline/config/")

    def run_dir(self, run_id: str) -> Path:
        if not RUN_ID_RE.match(run_id) or run_id in {".", ".."}:
            raise RepositoryError("Invalid run id")
        resolved = (self.runs_root / run_id).resolve()
        try:
            resolved.relative_to(self.runs_root)
        except ValueError as exc:
            raise RepositoryError("Invalid run id") from exc
        if not resolved.exists() or not resolved.is_dir():
            raise FileNotFoundError(run_id)
        return resolved

    def resolve_run_relative(self, run_id: str, rel: str) -> ResolvedPath:
        run_dir = self.run_dir(run_id)
        candidate = self._validate_relative(rel)
        if candidate.parts and candidate.parts[0] == "output":
            return self.resolve_output_relative(rel)
        resolved = self._contain("output", self.output_root, run_dir / candidate)
        try:
            resolved.path.relative_to(run_dir)
        except ValueError as exc:
            raise RepositoryError("Run artifact path escapes the run") from exc
        return resolved

    def safe_output_ref(self, value: Any) -> str:
        if not isinstance(value, str) or not value:
            return ""
        try:
            path = Path(value)
            if path.is_absolute():
                resolved = path.resolve()
                try:
                    return "output/" + resolved.relative_to(self.output_root).as_posix()
                except ValueError:
                    return ""
            resolved = self.resolve_output_relative(value)
            return "output/" + resolved.rel
        except (OSError, RepositoryError):
            return ""

    def read_json_file(self, path: Path) -> tuple[Any | None, str | None]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle), None
        except json.JSONDecodeError as exc:
            return None, f"Malformed JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}"
        except FileNotFoundError:
            return None, "Missing"
        except UnicodeDecodeError:
            return None, "Not UTF-8 text"

    def read_json_rel(self, run_id: str, rel: str) -> tuple[Any | None, str | None]:
        resolved = self.resolve_run_relative(run_id, rel)
        return self.read_json_file(resolved.path)

    def list_runs(self) -> list[dict[str, Any]]:
        if not self.runs_root.exists():
            return []
        runs: list[dict[str, Any]] = []
        current_id = self.current_run_id()
        for run_dir in sorted((p for p in self.runs_root.iterdir() if p.is_dir()), reverse=True):
            if not RUN_ID_RE.match(run_dir.name):
                continue
            runs.append(self.run_index_entry(run_dir.name, current_id))
        return runs

    def current_run_id(self) -> str:
        path = self.output_root / "current_run.json"
        data, _ = self.read_json_file(path)
        if isinstance(data, dict):
            value = data.get("run_id") or data.get("current_run_id")
            if isinstance(value, str):
                return value
        return ""

    def run_index_entry(self, run_id: str, current_id: str = "") -> dict[str, Any]:
        run_dir = self.run_dir(run_id)
        context, context_error = self.read_json_file(run_dir / "run_context.json")
        state, state_error = self.read_json_file(run_dir / "orchestration" / "run_state.json")
        context = context if isinstance(context, dict) else {}
        state = state if isinstance(state, dict) else {}
        stage_status = self._stage_statuses(state)
        summaries = self._summary_metrics(run_id)
        last_module = self._last_completed_module(state)
        failure_reason = self._failure_reason(state, summaries)
        stat = run_dir.stat()
        return {
            "run_id": run_id,
            "is_current": run_id == current_id,
            "created_at": context.get("created_at") or self._created_from_run_id(run_id),
            "mtime": stat.st_mtime,
            "profile": context.get("run_profile") or state.get("run_profile") or "",
            "environment": context.get("config_environment") or "",
            "trigger": context.get("trigger") or "",
            "stage_status": stage_status,
            "overall_status": self._overall_status(stage_status, failure_reason, [context_error, state_error]),
            "last_completed_module": last_module,
            "failure_reason": failure_reason,
            "metrics": summaries,
            "problems": [error for error in [context_error, state_error] if error and error != "Missing"],
        }

    def run_detail(self, run_id: str) -> dict[str, Any]:
        run_dir = self.run_dir(run_id)
        context, context_error = self.read_json_file(run_dir / "run_context.json")
        state, state_error = self.read_json_file(run_dir / "orchestration" / "run_state.json")
        context = context if isinstance(context, dict) else {}
        state = state if isinstance(state, dict) else {}
        modules = self.modules_for_run(run_id, state)
        return {
            "index": self.run_index_entry(run_id, self.current_run_id()),
            "context": self._trim_context(context),
            "state": self._trim_state(state),
            "modules": modules,
            "artifact_tree": [],
            "artifact_tree_deferred": True,
            "errors": {"run_context": context_error, "run_state": state_error},
        }

    def workflow(self, run_id: str) -> dict[str, Any]:
        state, state_error = self.read_json_rel(run_id, "orchestration/run_state.json")
        state = state if isinstance(state, dict) else {}
        modules = self.modules_for_run(run_id, state)
        module_index = {module["name"]: module for module in modules}
        state_stages = state.get("stages") if isinstance(state.get("stages"), dict) else {}
        stages = []
        for stage_order, stage_name in enumerate(("ingestion", "content", "voiceover", "visuals"), start=1):
            stage_state = state_stages.get(stage_name) if isinstance(state_stages, dict) else {}
            stage_state = stage_state if isinstance(stage_state, dict) else {}
            state_order = stage_state.get("module_order")
            names = list(state_order) if isinstance(state_order, list) else list(STAGE_MODULES.get(stage_name, []))
            for fallback_name in STAGE_MODULES.get(stage_name, []):
                if fallback_name not in names:
                    names.append(fallback_name)
            stage_modules = [
                self._workflow_module(run_id, module_index.get(name) or {
                    "name": name,
                    "stage": stage_name,
                    "status": "missing",
                    "path": MODULE_PATHS.get(name, name),
                    "summary": {},
                    "artifacts": [],
                }, sequence=index)
                for index, name in enumerate(names, start=1)
            ]
            stage_status = stage_state.get("status") or self._aggregate_status(
                [module.get("status", "missing") for module in stage_modules]
            )
            started_at = stage_state.get("started_at", "")
            completed_at = stage_state.get("completed_at", "")
            invocation_count = stage_state.get("invocation_count", 0)
            definition = STAGE_CATALOG[stage_name]
            stages.append({
                "key": stage_name,
                "order": stage_order,
                **definition,
                "status": stage_status,
                "started_at": started_at,
                "completed_at": completed_at,
                "invocation_count": invocation_count,
                "module_count": len(stage_modules),
                "completed_module_count": sum(
                    module.get("status") in {"ok", "partial", "ready", "present"}
                    for module in stage_modules
                ),
                "modules": stage_modules,
            })
        return {
            "run_id": run_id,
            "updated_at": state.get("updated_at", ""),
            "read_only": True,
            "state_error": state_error if state_error != "Missing" else None,
            "stages": stages,
        }

    def record_page(
        self,
        run_id: str,
        *,
        search: str = "",
        outcome: str = "all",
        offset: int = 0,
        limit: int = 30,
    ) -> dict[str, Any]:
        rows = self._record_index(run_id)
        counts: dict[str, int] = {"all": len(rows)}
        for row in rows:
            bucket = str(row.get("outcome") or "unresolved")
            counts[bucket] = counts.get(bucket, 0) + 1
        if search:
            needle = search.casefold()
            rows = [
                row for row in rows
                if needle in " ".join(
                    str(row.get(key, ""))
                    for key in ("title", "source", "source_group", "record_id", "record_key", "story_title")
                ).casefold()
            ]
        if outcome and outcome != "all":
            rows = [row for row in rows if row.get("outcome") == outcome]
        total = len(rows)
        offset = max(0, offset)
        limit = max(1, min(limit, 100))
        page = rows[offset:offset + limit]
        return {
            "run_id": run_id,
            "offset": offset,
            "limit": limit,
            "total": total,
            "next_offset": offset + len(page) if offset + len(page) < total else None,
            "counts": counts,
            "records": page,
        }

    def record_lineage(self, run_id: str, record_ref: str) -> dict[str, Any]:
        if not RUN_ID_RE.match(record_ref):
            raise RepositoryError("Invalid record reference")
        rows = self._record_index(run_id)
        summary = next(
            (
                row for row in rows
                if record_ref in {row.get("record_key"), row.get("record_id"), row.get("candidate_key")}
            ),
            None,
        )
        if summary is None:
            raise FileNotFoundError(record_ref)
        return self._record_lineage_detail(run_id, summary)

    def modules_for_run(self, run_id: str, state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        run_dir = self.run_dir(run_id)
        state = state or {}
        state_modules: dict[str, Any] = {}
        if isinstance(state.get("stages"), dict):
            for stage_name, stage in state["stages"].items():
                for module_name, module_state in (stage.get("modules") or {}).items():
                    state_modules[module_name] = {"stage": stage_name, **module_state}
        modules: list[dict[str, Any]] = []
        seen: set[str] = set()
        for stage, names in STAGE_MODULES.items():
            for name in names:
                if name == "voiceover":
                    variants = self.voiceovers(run_id)
                    modules.append({
                        "name": "voiceover",
                        "stage": "voiceover",
                        "status": state_modules.get("voiceover", {}).get("status") or ("ok" if variants else "missing"),
                        "path": "voiceover",
                        "variant_count": len(variants),
                        "summary": self._summary_preview(
                            state_modules.get("voiceover", {}).get("summary")
                            or (variants[0].get("summary") if variants else {})
                        ),
                        "artifacts": self._module_artifacts(run_dir / "voiceover", "voiceover"),
                        "reused": state_modules.get("voiceover", {}).get("reused", False),
                    })
                    seen.add(name)
                    continue
                rel = MODULE_PATHS.get(name, name)
                module_dir = run_dir / rel
                state_info = state_modules.get(name, {})
                summary, summary_error = self.read_json_file(module_dir / "summary.json")
                if not isinstance(summary, dict):
                    summary = state_info.get("summary") if isinstance(state_info.get("summary"), dict) else {}
                modules.append({
                    "name": name,
                    "stage": state_info.get("stage") or stage,
                    "status": state_info.get("status") or ("ok" if module_dir.exists() else "missing"),
                    "path": rel,
                    "summary": self._summary_preview(summary),
                    "summary_error": summary_error if summary_error != "Missing" else None,
                    "reused": state_info.get("reused", False),
                    "recorded_at": state_info.get("recorded_at", ""),
                    "result_path": self.safe_output_ref(state_info.get("result_path")),
                    "artifacts": self._module_artifacts(module_dir, rel),
                })
                seen.add(name)
        for rel in self._top_level_module_dirs(run_dir):
            name = rel.replace("/", "_")
            if name in seen or name in MODULE_PATHS:
                continue
            modules.append({
                "name": name,
                "stage": "other",
                "status": "present",
                "path": rel,
                "summary": {},
                "artifacts": self._module_artifacts(run_dir / rel, rel),
            })
        return modules

    def module_detail(self, run_id: str, module: str) -> dict[str, Any]:
        run_dir = self.run_dir(run_id)
        rel = MODULE_PATHS.get(module, module)
        module_dir = (run_dir / rel).resolve()
        try:
            module_dir.relative_to(run_dir)
        except ValueError as exc:
            raise RepositoryError("Invalid module path") from exc
        if not module_dir.exists():
            return {
                "name": module,
                "path": rel,
                "status": "missing",
                "definition": MODULE_CATALOG.get(module, {}),
                "artifacts": [],
                "raw_sources": [],
            }
        summary, summary_error = self.read_json_file(module_dir / "summary.json")
        curated = self.curated_module(run_id, module)
        state, _ = self.read_json_file(run_dir / "orchestration" / "run_state.json")
        module_state = next(
            (
                item
                for item in self.modules_for_run(
                    run_id,
                    state if isinstance(state, dict) else {},
                )
                if item.get("name") == module
            ),
            {},
        )
        activity = self._module_activity(run_id, module, module_state.get("stage", ""), module_dir)
        return {
            "name": module,
            "path": rel,
            "status": module_state.get("status") or "present",
            "stage": module_state.get("stage", ""),
            "reused": module_state.get("reused", False),
            "recorded_at": module_state.get("recorded_at", ""),
            "definition": MODULE_CATALOG.get(module, {}),
            "summary": self._summary_preview(summary if isinstance(summary, dict) else {}),
            "summary_error": summary_error if summary_error != "Missing" else None,
            "artifacts": self._module_artifacts(module_dir, rel, deep=True),
            "raw_sources": self._module_sources(module_dir, rel),
            "activity": activity,
            "generation_evidence": {
                "llm_ledger_persisted": bool(activity.get("llm_ledger")),
                "tts_ledger_persisted": bool(activity.get("tts_variants")),
                "classification_source": "inspector_catalog",
            },
            "curated": curated,
        }

    def voiceovers(self, run_id: str) -> list[dict[str, Any]]:
        run_dir = self.run_dir(run_id)
        voice_root = run_dir / "voiceover"
        if not voice_root.exists():
            return []
        variants: list[dict[str, Any]] = []
        for variant_dir in sorted(p for p in voice_root.iterdir() if p.is_dir()):
            package, package_error = self.read_json_file(variant_dir / "voiceover_package.json")
            summary, _ = self.read_json_file(variant_dir / "summary.json")
            package = package if isinstance(package, dict) else {}
            summary = summary if isinstance(summary, dict) else {}
            audio = package.get("audio") if isinstance(package.get("audio"), dict) else {}
            captions = package.get("captions") if isinstance(package.get("captions"), dict) else {}
            style = package.get("style") if isinstance(package.get("style"), dict) else {}
            provider_settings = style.get("provider_settings") if isinstance(style.get("provider_settings"), dict) else {}
            mastering = audio.get("mastering") if isinstance(audio.get("mastering"), dict) else {}
            output_measurement = mastering.get("output_measurement") if isinstance(mastering.get("output_measurement"), dict) else {}
            full_audio = self.safe_output_ref(audio.get("full_audio_path") or summary.get("audio_path"))
            variants.append({
                "variant_id": variant_dir.name,
                "status": package.get("status") or summary.get("status") or ("malformed" if package_error else "present"),
                "provider": package.get("provider") or summary.get("provider") or "",
                "voice": package.get("voice") or summary.get("voice") or "",
                "style": package.get("style") if isinstance(package.get("style"), str) else style.get("name", ""),
                "style_description": style.get("description", ""),
                "speed": style.get("speed"),
                "model": provider_settings.get("model", ""),
                "duration_seconds": audio.get("duration_seconds") or summary.get("duration_seconds"),
                "sample_rate_hz": audio.get("sample_rate_hz"),
                "mastering_status": mastering.get("status", ""),
                "integrated_lufs": output_measurement.get("integrated_lufs"),
                "true_peak_db": output_measurement.get("true_peak_db"),
                "audio_path": full_audio,
                "captions": {
                    "srt": self.safe_output_ref(captions.get("srt_path") or variant_dir.joinpath("captions/captions.srt").as_posix()),
                    "vtt": self.safe_output_ref(captions.get("vtt_path") or variant_dir.joinpath("captions/captions.vtt").as_posix()),
                },
                "unit_count": len(package.get("audio_units") or []),
                "chunk_count": len(package.get("chunks") or []) or summary.get("chunk_count"),
                "summary": self._sanitize_value(summary),
                "package_error": package_error if package_error != "Missing" else None,
            })
        return variants

    def voiceover_detail(self, run_id: str, variant_id: str) -> dict[str, Any]:
        self._validate_relative(variant_id)
        package, package_error = self.read_json_rel(run_id, f"voiceover/{variant_id}/voiceover_package.json")
        package = package if isinstance(package, dict) else {}
        return {
            "variant": next((v for v in self.voiceovers(run_id) if v["variant_id"] == variant_id), None),
            "audio_units": self._sanitize_value(package.get("audio_units") or []),
            "chunks": self._sanitize_value(package.get("chunks") or []),
            "audio": self._sanitize_value(package.get("audio") or {}),
            "style": self._sanitize_value(package.get("style") or {}),
            "captions": self._sanitize_value(package.get("captions") or {}),
            "alignment": self._sanitize_value(package.get("alignment") or {}),
            "provenance": self._sanitize_value(package.get("provenance") or {}),
            "error": package_error,
        }

    def visual_scenes(self, run_id: str) -> dict[str, Any]:
        result, result_error = self.read_json_rel(run_id, "orchestration/visuals_stage_result.json")
        result = result if isinstance(result, dict) else {}
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        handoff = result.get("handoff") if isinstance(result.get("handoff"), dict) else {}
        rendered = bool(summary.get("rendered", handoff.get("episode_rendered", False)))
        return {
            "status": result.get("status", ""),
            "summary": self._sanitize_value({
                "engine": summary.get("engine", ""),
                "art_director": summary.get("art_director", ""),
                "units": summary.get("units"),
                "rendered": rendered,
            }),
            "final_video": self.safe_output_ref(
                "output/runs/" + run_id + "/visuals/" + run_id + "-ad.mp4"
            ),
            "voiceover_package_path": data.get("voiceover_package_path", ""),
            "failure_reason": summary.get("failure_reason", ""),
            "result_error": result_error if result_error != "Missing" else None,
        }

    def artifact_tree(self, run_id: str) -> list[dict[str, Any]]:
        run_dir = self.run_dir(run_id)
        return self._tree_for_dir(run_dir, run_dir, max_depth=4)

    def artifact_content(self, run_id: str, rel: str, max_bytes: int = 2_000_000) -> dict[str, Any]:
        resolved = self.resolve_run_relative(run_id, rel)
        if not resolved.path.exists() or not resolved.path.is_file():
            raise FileNotFoundError(rel)
        suffix = resolved.path.suffix.lower()
        stat = resolved.path.stat()
        if suffix not in TEXT_EXTENSIONS and suffix not in MEDIA_EXTENSIONS:
            return {"path": "output/" + resolved.rel, "kind": "binary", "size": stat.st_size, "truncated": False}
        if suffix in MEDIA_EXTENSIONS:
            return {
                "path": "output/" + resolved.rel,
                "kind": "media",
                "mime_type": mimetypes.guess_type(resolved.path.name)[0] or "application/octet-stream",
                "size": stat.st_size,
                "truncated": False,
            }
        with resolved.path.open("rb") as handle:
            data = handle.read(max_bytes + 1)
        truncated = len(data) > max_bytes
        text = self._sanitize_text(data[:max_bytes].decode("utf-8", errors="replace"))
        body: dict[str, Any] = {
            "path": "output/" + resolved.rel,
            "kind": "text",
            "size": stat.st_size,
            "truncated": truncated,
            "text": text,
        }
        if suffix == ".json" and not truncated:
            try:
                body["json"] = self._sanitize_value(json.loads(text))
                body["kind"] = "json"
            except json.JSONDecodeError as exc:
                body["parse_error"] = f"Malformed JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}"
        return body

    def log_content(self, run_id: str, stage: str, search: str = "", severity: str = "", tail: int = 500) -> dict[str, Any]:
        if not RUN_ID_RE.match(stage):
            raise RepositoryError("Invalid stage")
        resolved = self.resolve_run_relative(run_id, f"orchestration/logs/{stage}.log")
        lines = self._read_tail_lines(resolved.path, max(1, min(tail, 5000)))
        if severity:
            lines = [line for line in lines if severity.upper() in line.upper()]
        if search:
            lines = [line for line in lines if search.lower() in line.lower()]
        return {"stage": stage, "path": "output/" + resolved.rel, "lines": [self._sanitize_text(line) for line in lines], "line_count": len(lines)}

    def jsonl_page(self, run_id: str, module: str, ledger: str = "llm_calls", offset: int = 0, limit: int = 25, include_payload: bool = False) -> dict[str, Any]:
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        if ledger == "tts":
            rel = f"voiceover/{module}/tts_requests.jsonl"
        else:
            rel = f"{MODULE_PATHS.get(module, module)}/llm_calls.jsonl"
        resolved = self.resolve_run_relative(run_id, rel)
        rows: list[dict[str, Any]] = []
        errors: list[str] = []
        total = 0
        with resolved.path.open("r", encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if not line.strip():
                    continue
                total += 1
                if index < offset or len(rows) >= limit:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(f"line {index + 1}: {exc.msg}")
                    record = {"parse_error": exc.msg}
                rows.append(self._ledger_row(record, index, include_payload))
        return {
            "path": "output/" + resolved.rel,
            "offset": offset,
            "limit": limit,
            "total": total,
            "next_offset": offset + len(rows) if offset + len(rows) < total else None,
            "rows": rows,
            "errors": errors,
        }

    def jsonl_record(self, run_id: str, module: str, index: int, ledger: str = "llm_calls") -> dict[str, Any]:
        page = self.jsonl_page(run_id, module, ledger=ledger, offset=index, limit=1, include_payload=True)
        if not page["rows"]:
            raise FileNotFoundError(str(index))
        return page["rows"][0]

    def config_manifest(self) -> dict[str, Any]:
        files = []
        if self.config_root.exists():
            for path in sorted(p for p in self.config_root.rglob("*") if p.is_file()):
                try:
                    resolved = self._contain("config", self.config_root, path)
                except RepositoryError:
                    continue
                if path.suffix.lower() in {".yaml", ".yml"}:
                    files.append({"path": "src/pipeline/config/" + resolved.rel, "name": path.name, "size": path.stat().st_size})
        return {"root": "src/pipeline/config", "files": files}

    def config_source(self, rel: str) -> dict[str, Any]:
        resolved = self.resolve_config_relative(rel)
        if not resolved.path.is_file():
            raise FileNotFoundError(rel)
        if resolved.path.suffix.lower() not in {".yaml", ".yml", ".json"}:
            raise RepositoryError("Only YAML and JSON config files are exposed")
        text = self._sanitize_text(resolved.path.read_text(encoding="utf-8", errors="replace"))
        return {"path": "src/pipeline/config/" + resolved.rel, "text": text, "size": resolved.path.stat().st_size}

    def run_config(self, run_id: str) -> dict[str, Any]:
        run_dir = self.run_dir(run_id)
        context, context_error = self.read_json_file(run_dir / "run_context.json")
        frozen = context.get("profile_config") if isinstance(context, dict) else None
        snapshots = []
        for module in self.modules_for_run(run_id):
            rel = module.get("path", "")
            snapshot_path = run_dir / rel / "config_snapshot.json"
            if snapshot_path.exists():
                data, error = self.read_json_file(snapshot_path)
                snapshots.append({
                    "module": module.get("name"),
                    "path": f"output/runs/{run_id}/{rel}/config_snapshot.json",
                    "config": self._sanitize_value(data if isinstance(data, (dict, list)) else None),
                    "error": error,
                })
        current_files = self.config_manifest()["files"]
        diffs = []
        profile = context.get("run_profile") if isinstance(context, dict) else ""
        if isinstance(frozen, dict) and profile:
            for cfg in current_files:
                path = cfg["path"]
                if f"/profiles/{profile}/" not in path and not path.endswith("workbench.yaml"):
                    continue
                try:
                    current = self.config_source(path)["text"].splitlines()
                except Exception:
                    continue
                key = Path(path).stem
                frozen_piece = frozen.get(key)
                if frozen_piece is None:
                    stage = Path(path).parent.name
                    frozen_piece = (frozen.get(stage) or {}).get(key) if isinstance(frozen.get(stage), dict) else None
                frozen_text = json.dumps(frozen_piece, indent=2, sort_keys=True).splitlines() if frozen_piece is not None else []
                diff = "\n".join(difflib.unified_diff(frozen_text, current, fromfile="frozen", tofile=path, lineterm=""))
                if diff:
                    diffs.append({"path": path, "diff": diff[:20000], "truncated": len(diff) > 20000})
        return {
            "frozen_profile": self._sanitize_value(frozen),
            "run_context_error": context_error,
            "module_snapshots": snapshots,
            "current_authoring": current_files,
            "diffs": diffs,
            "provider_model_summary": self._sanitize_value(self.provider_model_summary(run_id, frozen, snapshots)),
        }

    def provider_model_summary(self, run_id: str, frozen: Any, snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for snapshot in snapshots:
            config = snapshot.get("config")
            for path, value in self._walk(config):
                if isinstance(value, dict) and value.get("model"):
                    rows.append({
                        "module": snapshot.get("module"),
                        "path": ".".join(path),
                        "provider": value.get("provider", ""),
                        "model": value.get("model", ""),
                    })
        return rows[:200]

    def compare_runs(self, left_run_id: str, right_run_id: str) -> dict[str, Any]:
        if left_run_id == right_run_id:
            raise RepositoryError("Choose two different runs to compare")
        left = self.run_index_entry(left_run_id, self.current_run_id())
        right = self.run_index_entry(right_run_id, self.current_run_id())
        left_modules = {item["name"]: item for item in self.modules_for_run(left_run_id)}
        right_modules = {item["name"]: item for item in self.modules_for_run(right_run_id)}
        module_names = list(dict.fromkeys([
            *[name for names in STAGE_MODULES.values() for name in names],
            *left_modules,
            *right_modules,
        ]))
        module_matrix = [
            {
                "module": name,
                "label": MODULE_CATALOG.get(name, {}).get("label", name.replace("_", " ").title()),
                "left_status": left_modules.get(name, {}).get("status", "missing"),
                "right_status": right_modules.get(name, {}).get("status", "missing"),
                "left_reused": bool(left_modules.get(name, {}).get("reused")),
                "right_reused": bool(right_modules.get(name, {}).get("reused")),
                "changed": (
                    left_modules.get(name, {}).get("status", "missing")
                    != right_modules.get(name, {}).get("status", "missing")
                    or bool(left_modules.get(name, {}).get("reused"))
                    != bool(right_modules.get(name, {}).get("reused"))
                ),
            }
            for name in module_names
        ]
        script = self._compare_scripts(left_run_id, right_run_id)
        metadata = self._compare_metadata(left_run_id, right_run_id)
        config = self._compare_frozen_config(left_run_id, right_run_id)
        return {
            "left": left,
            "right": right,
            "metrics": self._metric_comparison(left.get("metrics") or {}, right.get("metrics") or {}),
            "modules": module_matrix,
            "script": script,
            "metadata": metadata,
            "voiceover": {
                "left": self.voiceovers(left_run_id),
                "right": self.voiceovers(right_run_id),
            },
            "usage": {
                "left": self._usage_summary(left_run_id),
                "right": self._usage_summary(right_run_id),
                "cost_note": "Persisted ledgers do not currently contain currency cost, so this comparison reports calls, tokens, latency, and synthesis requests without inventing a dollar estimate.",
            },
            "config": config,
        }

    def llm_provenance(
        self,
        run_id: str,
        module: str,
        *,
        record_key: str = "",
        story_id: str = "",
        section_id: str = "",
        limit: int = 50,
    ) -> dict[str, Any]:
        self.run_dir(run_id)
        if module not in MODULE_PATHS:
            raise RepositoryError("Unknown pipeline module")
        for value in (record_key, story_id, section_id):
            if value and not RUN_ID_RE.fullmatch(value):
                raise RepositoryError("Invalid provenance identifier")
        ledger_rel = f"{MODULE_PATHS[module]}/llm_calls.jsonl"
        resolved = self.resolve_run_relative(run_id, ledger_rel)
        if not resolved.path.is_file():
            raise FileNotFoundError(ledger_rel)
        targets = {
            "record_key": record_key,
            "story_id": story_id,
            "section_id": section_id,
        }
        targets = {key: value for key, value in targets.items() if value}
        matches: list[dict[str, Any]] = []
        scanned = 0
        malformed = 0
        with resolved.path.open("r", encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if not line.strip():
                    continue
                scanned += 1
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    malformed += 1
                    continue
                metadata = record.get("metadata") if isinstance(record, dict) else {}
                reasons = self._provenance_match_reasons(metadata, targets)
                if targets and not reasons:
                    continue
                matches.append({
                    "index": index,
                    "module_name": self._sanitize_text(str(record.get("module_name") or "")),
                    "provider": record.get("provider", ""),
                    "model": record.get("model", ""),
                    "duration_seconds": record.get("duration_seconds"),
                    "usage": self._sanitize_value(record.get("usage") or {}),
                    "metadata": self._sanitize_value(metadata or {}),
                    "match_reasons": reasons,
                })
                if len(matches) >= max(1, min(limit, 200)):
                    break
        return {
            "run_id": run_id,
            "module": module,
            "precision": "contextual",
            "precision_note": (
                "Matches use identifiers persisted in call metadata. They identify calls that handled this record, "
                "story, or section, but the artifact does not persist a field-level call ID."
            ),
            "targets": targets,
            "scanned": scanned,
            "malformed": malformed,
            "matches": matches,
        }

    def _metric_comparison(
        self,
        left: dict[str, Any],
        right: dict[str, Any],
    ) -> list[dict[str, Any]]:
        keys = [
            "collected_record_count",
            "prepared_record_count",
            "selected_story_count",
            "script_word_count",
            "audio_duration_seconds",
            "final_video_available",
        ]
        return [
            {
                "key": key,
                "left": left.get(key),
                "right": right.get(key),
                "changed": left.get(key) != right.get(key),
            }
            for key in keys
        ]

    def _compare_scripts(self, left_run_id: str, right_run_id: str) -> dict[str, Any]:
        left = self.curated_module(left_run_id, "script_generation")
        right = self.curated_module(right_run_id, "script_generation")
        left_text = str(left.get("full_script") or "")
        right_text = str(right.get("full_script") or "")
        left_sections = self._section_comparison_index(left.get("sections") or [])
        right_sections = self._section_comparison_index(right.get("sections") or [])
        section_ids = list(dict.fromkeys([*left_sections, *right_sections]))
        sections = [
            {
                "section_id": section_id,
                "left_title": left_sections.get(section_id, {}).get("title", ""),
                "right_title": right_sections.get(section_id, {}).get("title", ""),
                "left_words": left_sections.get(section_id, {}).get("word_count"),
                "right_words": right_sections.get(section_id, {}).get("word_count"),
                "changed": (
                    left_sections.get(section_id, {}).get("narration", "")
                    != right_sections.get(section_id, {}).get("narration", "")
                ),
            }
            for section_id in section_ids
        ]
        diff = "\n".join(difflib.unified_diff(
            left_text.splitlines(),
            right_text.splitlines(),
            fromfile=left_run_id,
            tofile=right_run_id,
            lineterm="",
        ))
        return {
            "left_word_count": len(left_text.split()),
            "right_word_count": len(right_text.split()),
            "left_fingerprint": left.get("fingerprint", ""),
            "right_fingerprint": right.get("fingerprint", ""),
            "changed": left_text != right_text,
            "sections": sections,
            "diff": diff[:80_000],
            "diff_truncated": len(diff) > 80_000,
        }

    def _compare_metadata(self, left_run_id: str, right_run_id: str) -> dict[str, Any]:
        left_final = self.curated_module(left_run_id, "metadata_finalizer")
        right_final = self.curated_module(right_run_id, "metadata_finalizer")
        left_created = self.curated_module(left_run_id, "metadata_creator")
        right_created = self.curated_module(right_run_id, "metadata_creator")
        left = left_final.get("youtube_metadata") or left_created.get("youtube_metadata") or {}
        right = right_final.get("youtube_metadata") or right_created.get("youtube_metadata") or {}
        fields = [
            "title_options",
            "description",
            "description_draft",
            "tags",
            "thumbnail_concepts",
            "thumbnail_text_options",
            "chapters",
            "source_urls",
        ]
        return {
            "fields": [
                {
                    "key": key,
                    "left": self._sanitize_value(left.get(key)),
                    "right": self._sanitize_value(right.get(key)),
                    "changed": left.get(key) != right.get(key),
                }
                for key in fields
            ]
        }

    def _compare_frozen_config(self, left_run_id: str, right_run_id: str) -> dict[str, Any]:
        left_context, left_error = self.read_json_rel(left_run_id, "run_context.json")
        right_context, right_error = self.read_json_rel(right_run_id, "run_context.json")
        left_profile = left_context.get("profile_config") if isinstance(left_context, dict) else {}
        right_profile = right_context.get("profile_config") if isinstance(right_context, dict) else {}
        left_profile = left_profile if isinstance(left_profile, dict) else {}
        right_profile = right_profile if isinstance(right_profile, dict) else {}
        keys = sorted(set(left_profile) | set(right_profile))
        left_text = json.dumps(left_profile, indent=2, sort_keys=True, ensure_ascii=True)
        right_text = json.dumps(right_profile, indent=2, sort_keys=True, ensure_ascii=True)
        diff = "\n".join(difflib.unified_diff(
            left_text.splitlines(),
            right_text.splitlines(),
            fromfile=f"{left_run_id}/frozen",
            tofile=f"{right_run_id}/frozen",
            lineterm="",
        ))
        return {
            "changed_sections": [
                key for key in keys if left_profile.get(key) != right_profile.get(key)
            ],
            "diff": diff[:120_000],
            "diff_truncated": len(diff) > 120_000,
            "left_error": left_error if left_error != "Missing" else None,
            "right_error": right_error if right_error != "Missing" else None,
        }

    def _usage_summary(self, run_id: str) -> dict[str, Any]:
        run_dir = self.run_dir(run_id)
        llm = {
            "call_count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "duration_seconds": 0.0,
            "malformed_rows": 0,
            "routes": {},
        }
        tts = {
            "request_count": 0,
            "latency_seconds": 0.0,
            "malformed_rows": 0,
            "routes": {},
        }
        for path in run_dir.rglob("llm_calls.jsonl"):
            self._aggregate_ledger(path, llm, kind="llm")
        for path in run_dir.rglob("tts_requests.jsonl"):
            self._aggregate_ledger(path, tts, kind="tts")
        llm["duration_seconds"] = round(float(llm["duration_seconds"]), 3)
        tts["latency_seconds"] = round(float(tts["latency_seconds"]), 3)
        llm["routes"] = [
            {"route": key, "count": count}
            for key, count in sorted(llm["routes"].items())
        ]
        tts["routes"] = [
            {"route": key, "count": count}
            for key, count in sorted(tts["routes"].items())
        ]
        return {"llm": llm, "tts": tts}

    def _aggregate_ledger(self, path: Path, result: dict[str, Any], *, kind: str) -> None:
        try:
            resolved = path.resolve()
            resolved.relative_to(self.output_root)
        except (OSError, ValueError):
            return
        with resolved.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    result["malformed_rows"] += 1
                    continue
                provider = str(row.get("provider") or "unknown")
                model = str(row.get("model") or "unknown")
                route = f"{provider} / {model}"
                result["routes"][route] = result["routes"].get(route, 0) + 1
                if kind == "llm":
                    usage = row.get("usage") if isinstance(row.get("usage"), dict) else {}
                    prompt = usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0
                    completion = usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
                    total = usage.get("total_tokens", 0) or (prompt + completion)
                    result["call_count"] += 1
                    result["prompt_tokens"] += self._number(prompt)
                    result["completion_tokens"] += self._number(completion)
                    result["total_tokens"] += self._number(total)
                    result["duration_seconds"] += self._number(row.get("duration_seconds"))
                else:
                    result["request_count"] += 1
                    result["latency_seconds"] += self._number(row.get("latency_seconds"))

    def _provenance_match_reasons(
        self,
        metadata: Any,
        targets: dict[str, str],
    ) -> list[str]:
        if not targets:
            return ["module ledger"]
        flattened = list(self._walk(metadata if isinstance(metadata, (dict, list)) else {}))
        reasons: list[str] = []
        for target_name, target_value in targets.items():
            for path, value in flattened:
                if isinstance(value, str) and value == target_value:
                    reasons.append(f"{target_name} matched metadata.{'.'.join(path)}")
                    break
                if isinstance(value, list) and target_value in value:
                    reasons.append(f"{target_name} matched metadata.{'.'.join(path)}")
                    break
        return reasons

    def _section_comparison_index(self, sections: list[Any]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for index, section in enumerate(sections):
            if not isinstance(section, dict):
                continue
            section_id = str(section.get("section_id") or f"section_{index + 1}")
            narration = str(section.get("narration_text") or "")
            if not narration:
                narration = " ".join(
                    str(beat.get("narration_text") or beat.get("text") or "")
                    for beat in (section.get("beats") or [])
                    if isinstance(beat, dict)
                ).strip()
            result[section_id] = {
                "title": section.get("story_title") or section.get("title") or section_id,
                "narration": narration,
                "word_count": section.get("word_count") or len(narration.split()),
            }
        return result

    @staticmethod
    def _number(value: Any) -> float | int:
        try:
            number = float(value or 0)
        except (TypeError, ValueError):
            return 0
        return int(number) if number.is_integer() else number

    def curated_module(self, run_id: str, module: str) -> dict[str, Any]:
        if module == "news_collection":
            summary, _ = self.read_json_rel(run_id, "news_collection/summary.json")
            raw, _ = self.read_json_rel(run_id, "news_collection/raw_records.json")
            summary = summary if isinstance(summary, dict) else {}
            raw = raw if isinstance(raw, dict) else {}
            return {
                "stats": self._pick(
                    summary,
                    "status",
                    "total_records",
                    "candidate_count",
                    "enabled_source_group_count",
                    "successful_source_group_count",
                    "elapsed_seconds",
                ),
                "source_groups": self._summarize_source_groups(summary.get("groups") or {}),
                "records": self._summarize_records(raw.get("records") or []),
            }
        if module == "evidence_prep":
            summary, _ = self.read_json_rel(run_id, "evidence_prep/summary.json")
            ledger, _ = self.read_json_rel(run_id, "evidence_prep/decision_ledger.json")
            summary = summary if isinstance(summary, dict) else {}
            ledger = ledger if isinstance(ledger, dict) else {}
            return {
                "stats": self._pick(
                    summary,
                    "status",
                    "input_record_count",
                    "prepared_record_count",
                    "excluded_count",
                    "duplicate_count",
                ),
                "decision_counts": self._sanitize_value(summary.get("decision_counts") or {}),
                "content_status_counts": self._sanitize_value(summary.get("content_status_counts") or {}),
                "warning_counts": self._sanitize_value(summary.get("preparation_warning_counts") or {}),
                "source_groups": self._named_rows(summary.get("source_groups") or {}),
                "decisions": self._summarize_evidence_decisions(ledger.get("decisions") or []),
            }
        if module == "editorial_triage":
            summary, _ = self.read_json_rel(run_id, "editorial_triage/summary.json")
            decisions, _ = self.read_json_rel(run_id, "editorial_triage/decisions.json")
            records, _ = self.read_json_rel(run_id, "evidence_prep/prepared_records.json")
            summary = summary if isinstance(summary, dict) else {}
            decisions = decisions if isinstance(decisions, dict) else {}
            records = records if isinstance(records, dict) else {}
            record_index = {
                record.get("record_key"): record
                for record in (records.get("records") or [])
                if isinstance(record, dict) and record.get("record_key")
            }
            return {
                "stats": self._pick(
                    summary,
                    "input_record_count",
                    "decision_count",
                    "resolved_count",
                    "unresolved_count",
                    "batch_count",
                    "failed_batch_count",
                    "llm_call_count",
                ),
                "action_counts": self._sanitize_value(summary.get("action_counts") or {}),
                "decisions": self._summarize_triage_decisions(decisions.get("decisions") or [], record_index),
            }
        if module == "story_mapping":
            data, _ = self.read_json_rel(run_id, "story_mapping/stories.json")
            summary, _ = self.read_json_rel(run_id, "story_mapping/summary.json")
            stories = data.get("stories") if isinstance(data, dict) else []
            return {
                "stats": self._summary_preview(summary if isinstance(summary, dict) else {}),
                "stories": self._summarize_stories(stories),
            }
        if module == "editorial_selection":
            data, _ = self.read_json_rel(run_id, "editorial_selection/editorial_slate.json")
            summary, _ = self.read_json_rel(run_id, "editorial_selection/summary.json")
            if isinstance(data, dict):
                all_stories, _ = self.read_json_rel(run_id, "story_mapping/stories.json")
                story_index = {
                    story.get("story_id"): story
                    for story in ((all_stories or {}).get("stories") or [])
                    if isinstance(story, dict) and story.get("story_id")
                } if isinstance(all_stories, dict) else {}
                return {
                    "selected_stories": self._summarize_stories(data.get("selected_stories") or []),
                    "reserve_stories": self._summarize_stories(data.get("reserve_stories") or data.get("reserve") or []),
                    "rejected_stories": self._summarize_rejections(data.get("rejected") or [], story_index),
                    "episode_thesis": data.get("episode_thesis", ""),
                    "episode_shape": data.get("episode_shape", ""),
                    "ordering_rationale": data.get("ordering_rationale", ""),
                    "human_review_warning": data.get("human_review_warning", ""),
                    "selection_summary": self._summary_preview(summary if isinstance(summary, dict) else {}),
                }
        if module == "video_packaging":
            data, _ = self.read_json_rel(run_id, "video_packaging/video_packet.json")
            if isinstance(data, dict):
                return {
                    "selected_format": data.get("selected_format", ""),
                    "story_count": data.get("story_count"),
                    "editorial_context": self._sanitize_value(data.get("editorial_context") or {}),
                    "format_contract": self._sanitize_value(data.get("format_contract") or {}),
                    "duration_policy": self._sanitize_value(data.get("duration_policy") or {}),
                    "stories": self._summarize_stories(data.get("stories") or []),
                }
        if module == "script_generation":
            data, _ = self.read_json_rel(run_id, "script_generation/script_package.json")
            if isinstance(data, dict):
                return {
                    "stats": self._sanitize_value(data.get("full_script_stats") or {}),
                    "episode_direction": self._sanitize_value(data.get("episode_direction") or {}),
                    "bookends": self._sanitize_value(data.get("bookends") or {}),
                    "sections": self._sanitize_value(data.get("sections") or []),
                    "full_script": self._sanitize_text(data.get("full_script", "")),
                    "review": self._sanitize_value(data.get("review") or {}),
                    "checks": self._sanitize_value(data.get("checks") or {}),
                    "fingerprint": (data.get("provenance") or {}).get("content_fingerprint") or (data.get("checks") or {}).get("content_fingerprint", ""),
                }
        if module in {"metadata_creator", "metadata_finalizer"}:
            rel = f"{MODULE_PATHS.get(module, module)}/metadata_package.json"
            data, _ = self.read_json_rel(run_id, rel)
            youtube = data.get("youtube_metadata") if isinstance(data, dict) else {}
            return {
                "youtube_metadata": self._sanitize_value(youtube or {}),
                "checks": self._sanitize_value(data.get("checks") or {}) if isinstance(data, dict) else {},
                "provenance": self._sanitize_value(data.get("provenance") or {}) if isinstance(data, dict) else {},
            }
        if module == "voiceover":
            return {"variants": self.voiceovers(run_id)}
        if module == "visuals":
            return self.visual_scenes(run_id)
        return {}

    def _workflow_module(self, run_id: str, module: dict[str, Any], sequence: int) -> dict[str, Any]:
        name = str(module.get("name", ""))
        definition = MODULE_CATALOG.get(name, {
            "label": name.replace("_", " ").title(),
            "purpose": "Inspect the persisted data produced by this module.",
            "consumes": "Upstream persisted artifacts",
            "produces": "Module result and handoff",
        })
        run_dir = self.run_dir(run_id)
        return {
            **module,
            **definition,
            "sequence": sequence,
            "artifact_count": self._count_artifact_nodes(module.get("artifacts") or []),
            "has_llm_calls": (run_dir / str(module.get("path", "")) / "llm_calls.jsonl").is_file(),
            "available_modes": [],
        }

    def _module_sources(self, module_dir: Path, rel: str) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        if not module_dir.exists():
            return sources
        for path in sorted(p for p in module_dir.rglob("*") if p.is_file()):
            if len(sources) >= 600:
                break
            try:
                resolved = path.resolve()
                resolved.relative_to(self.output_root)
                relative = path.relative_to(module_dir).as_posix()
                full_rel = f"{rel}/{relative}"
                self._ensure_not_denied(full_rel)
            except (OSError, ValueError, RepositoryError):
                continue
            role = self._artifact_role(relative)
            sources.append({
                "label": path.stem.replace("_", " ").replace("-", " ").title(),
                "path": full_rel,
                "role": role,
                "extension": path.suffix.lower(),
                "size": path.stat().st_size,
                "media": path.suffix.lower() in MEDIA_EXTENSIONS,
            })
        role_order = {"summary": 0, "input": 1, "primary": 2, "result": 3, "config": 4, "activity": 5, "media": 6, "artifact": 7}
        return sorted(sources, key=lambda item: (role_order.get(item["role"], 99), item["path"]))

    def _artifact_role(self, rel: str) -> str:
        name = Path(rel).name.lower()
        suffix = Path(rel).suffix.lower()
        if name == "summary.json" or name.endswith("_summary.json"):
            return "summary"
        if name == "config_snapshot.json":
            return "config"
        if name.endswith("_input.json"):
            return "input"
        if name in {"llm_calls.jsonl", "tts_requests.jsonl"} or suffix == ".log":
            return "activity"
        if name.endswith("_result.json"):
            return "result"
        if suffix in MEDIA_EXTENSIONS:
            return "media"
        primary_names = {
            "raw_records.json",
            "candidate_ledger.json",
            "prepared_records.json",
            "decision_ledger.json",
            "decisions.json",
            "stories.json",
            "editorial_slate.json",
            "video_packet.json",
            "script_package.json",
            "full_script.txt",
            "metadata_package.json",
            "youtube_metadata.json",
            "voiceover_package.json",
        }
        return "primary" if name in primary_names else "artifact"

    def _module_activity(
        self,
        run_id: str,
        module: str,
        stage: str,
        module_dir: Path,
    ) -> dict[str, Any]:
        run_dir = self.run_dir(run_id)
        llm_path = module_dir / "llm_calls.jsonl"
        log_path = run_dir / "orchestration" / "logs" / f"{stage}.log" if stage else Path()
        activity: dict[str, Any] = {
            "llm_ledger": f"{MODULE_PATHS.get(module, module)}/llm_calls.jsonl" if llm_path.is_file() else "",
            "log_stage": stage if stage and log_path.is_file() else "",
            "tts_variants": [],
        }
        if module == "voiceover":
            activity["tts_variants"] = [
                variant["variant_id"]
                for variant in self.voiceovers(run_id)
                if (run_dir / "voiceover" / variant["variant_id"] / "tts_requests.jsonl").is_file()
            ]
        return activity

    def _count_artifact_nodes(self, nodes: list[Any]) -> int:
        count = 0
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("type") == "file":
                count += 1
            count += self._count_artifact_nodes(node.get("children") or [])
        return count

    def _aggregate_status(self, statuses: list[str]) -> str:
        normalized = [status for status in statuses if status]
        if not normalized or all(status in {"missing", "not_started"} for status in normalized):
            return "not_started"
        if any(status in {"failed", "error", "malformed"} for status in normalized):
            return "failed"
        if any(status == "partial" for status in normalized):
            return "partial"
        if any(status in {"running", "in_progress"} for status in normalized):
            return "running"
        return "ok"

    def _record_index(self, run_id: str) -> list[dict[str, Any]]:
        raw_data, _ = self.read_json_rel(run_id, "news_collection/raw_records.json")
        evidence_data, _ = self.read_json_rel(run_id, "evidence_prep/decision_ledger.json")
        prepared_data, _ = self.read_json_rel(run_id, "evidence_prep/prepared_records.json")
        triage_data, _ = self.read_json_rel(run_id, "editorial_triage/decisions.json")
        stories_data, _ = self.read_json_rel(run_id, "story_mapping/stories.json")
        slate_data, _ = self.read_json_rel(run_id, "editorial_selection/editorial_slate.json")
        raw_records = raw_data.get("records") if isinstance(raw_data, dict) else []
        evidence = evidence_data.get("decisions") if isinstance(evidence_data, dict) else []
        prepared = prepared_data.get("records") if isinstance(prepared_data, dict) else []
        triage = triage_data.get("decisions") if isinstance(triage_data, dict) else []
        stories = stories_data.get("stories") if isinstance(stories_data, dict) else []
        evidence_by_id = {
            item.get("record_id"): item for item in evidence or []
            if isinstance(item, dict) and item.get("record_id")
        }
        prepared_by_key = {
            item.get("record_key"): item for item in prepared or []
            if isinstance(item, dict) and item.get("record_key")
        }
        prepared_by_candidate = {
            item.get("candidate_key"): item for item in prepared or []
            if isinstance(item, dict) and item.get("candidate_key")
        }
        triage_by_key = {
            item.get("record_key"): item for item in triage or []
            if isinstance(item, dict) and item.get("record_key")
        }
        story_by_record: dict[str, dict[str, Any]] = {}
        for story in stories or []:
            if not isinstance(story, dict):
                continue
            for record in story.get("records") or []:
                if isinstance(record, dict) and record.get("record_key"):
                    story_by_record[record["record_key"]] = story
        selection_by_story = self._selection_index(slate_data if isinstance(slate_data, dict) else {})
        rows: list[dict[str, Any]] = []
        for raw in raw_records or []:
            if not isinstance(raw, dict):
                continue
            record_id = str(raw.get("record_id") or "")
            evidence_decision = evidence_by_id.get(record_id, {})
            prepared_record = prepared_by_key.get(evidence_decision.get("record_key")) or prepared_by_candidate.get(raw.get("candidate_key")) or {}
            record_key = str(evidence_decision.get("record_key") or prepared_record.get("record_key") or "")
            triage_decision = triage_by_key.get(record_key, {})
            story = story_by_record.get(record_key, {})
            story_id = str(story.get("story_id") or "")
            selection = selection_by_story.get(story_id, {})
            evidence_action = str(evidence_decision.get("decision") or "not_processed")
            triage_action = str(triage_decision.get("recommended_action") or "")
            selection_action = str(selection.get("action") or "")
            if evidence_action in {"hard_reject", "duplicate"}:
                outcome = "filtered"
                latest_step = "evidence_prep"
            elif selection_action == "select":
                outcome = "selected"
                latest_step = "downstream_production"
            elif selection_action == "reserve":
                outcome = "reserve"
                latest_step = "editorial_selection"
            elif selection_action == "reject":
                outcome = "rejected"
                latest_step = "editorial_selection"
            elif triage_action == "quarantine":
                outcome = "quarantined"
                latest_step = "editorial_triage"
            elif story_id:
                outcome = "mapped"
                latest_step = "story_mapping"
            elif triage_action:
                outcome = "triaged"
                latest_step = "editorial_triage"
            elif evidence_action == "candidate":
                outcome = "prepared"
                latest_step = "evidence_prep"
            else:
                outcome = "unresolved"
                latest_step = "news_collection"
            rows.append({
                "record_ref": record_key or record_id or raw.get("candidate_key", ""),
                "record_id": record_id,
                "record_key": record_key,
                "candidate_key": raw.get("candidate_key", ""),
                "title": raw.get("title", ""),
                "source": raw.get("source_name") or raw.get("source", ""),
                "source_group": raw.get("source_group", ""),
                "published_at": raw.get("published_at", ""),
                "content_status": prepared_record.get("content_status") or raw.get("content_status", ""),
                "evidence_decision": evidence_action,
                "evidence_reasons": self._sanitize_value(evidence_decision.get("reason_codes") or []),
                "triage_action": triage_action,
                "triage_confidence": triage_decision.get("confidence"),
                "story_id": story_id,
                "story_title": story.get("story_title", ""),
                "selection_action": selection_action,
                "selection_role": selection.get("role", ""),
                "outcome": outcome,
                "latest_step": latest_step,
            })
        return rows

    def _selection_index(self, slate: dict[str, Any]) -> dict[str, dict[str, Any]]:
        selections: dict[str, dict[str, Any]] = {}
        for key, fallback_action in (("selected_stories", "select"), ("reserve_stories", "reserve")):
            for story in slate.get(key) or []:
                if not isinstance(story, dict) or not story.get("story_id"):
                    continue
                decision = story.get("editorial_selection") if isinstance(story.get("editorial_selection"), dict) else {}
                selections[story["story_id"]] = {"action": fallback_action, **decision}
        for rejection in slate.get("rejected") or []:
            if isinstance(rejection, dict) and rejection.get("story_id"):
                selections[rejection["story_id"]] = {"action": "reject", **rejection}
        return selections

    def _record_lineage_detail(self, run_id: str, summary: dict[str, Any]) -> dict[str, Any]:
        record_id = summary.get("record_id", "")
        record_key = summary.get("record_key", "")
        candidate_key = summary.get("candidate_key", "")
        raw_data, _ = self.read_json_rel(run_id, "news_collection/raw_records.json")
        evidence_data, _ = self.read_json_rel(run_id, "evidence_prep/decision_ledger.json")
        prepared_data, _ = self.read_json_rel(run_id, "evidence_prep/prepared_records.json")
        triage_data, _ = self.read_json_rel(run_id, "editorial_triage/decisions.json")
        stories_data, _ = self.read_json_rel(run_id, "story_mapping/stories.json")
        slate_data, _ = self.read_json_rel(run_id, "editorial_selection/editorial_slate.json")
        packet_data, _ = self.read_json_rel(run_id, "video_packaging/video_packet.json")
        script_data, _ = self.read_json_rel(run_id, "script_generation/script_package.json")
        metadata_data, _ = self.read_json_rel(run_id, "metadata_creator/metadata_package.json")
        final_metadata_data, _ = self.read_json_rel(run_id, "metadata_finalizer/metadata_package.json")
        raw_records = raw_data.get("records") if isinstance(raw_data, dict) else []
        raw_record = next(
            (
                item for item in raw_records or []
                if isinstance(item, dict) and (
                    item.get("record_id") == record_id or item.get("candidate_key") == candidate_key
                )
            ),
            {},
        )
        evidence_decisions = evidence_data.get("decisions") if isinstance(evidence_data, dict) else []
        evidence_decision = next(
            (
                item for item in evidence_decisions or []
                if isinstance(item, dict) and (
                    item.get("record_id") == record_id or (record_key and item.get("record_key") == record_key)
                )
            ),
            {},
        )
        prepared_records = prepared_data.get("records") if isinstance(prepared_data, dict) else []
        prepared_record = next(
            (
                item for item in prepared_records or []
                if isinstance(item, dict) and (
                    (record_key and item.get("record_key") == record_key)
                    or (candidate_key and item.get("candidate_key") == candidate_key)
                )
            ),
            {},
        )
        triage_decisions = triage_data.get("decisions") if isinstance(triage_data, dict) else []
        triage_decision = next(
            (
                item for item in triage_decisions or []
                if isinstance(item, dict) and item.get("record_key") == record_key
            ),
            {},
        )
        stories = stories_data.get("stories") if isinstance(stories_data, dict) else []
        story = next(
            (
                item for item in stories or []
                if isinstance(item, dict) and any(
                    isinstance(record, dict) and record.get("record_key") == record_key
                    for record in item.get("records") or []
                )
            ),
            {},
        )
        story_id = story.get("story_id", "")
        mapped_record = next(
            (
                item for item in story.get("records") or []
                if isinstance(item, dict) and item.get("record_key") == record_key
            ),
            {},
        ) if isinstance(story, dict) else {}
        selection = self._selection_index(slate_data if isinstance(slate_data, dict) else {}).get(story_id, {})
        packet_story = next(
            (
                item for item in (packet_data.get("stories") or [])
                if isinstance(item, dict) and item.get("story_id") == story_id
            ),
            {},
        ) if isinstance(packet_data, dict) else {}
        sections = script_data.get("sections") if isinstance(script_data, dict) else []
        matched_sections = []
        for section in sections or []:
            if not isinstance(section, dict):
                continue
            uses_record = record_key and record_key in (section.get("used_source_record_keys") or [])
            uses_story = story_id and story_id == section.get("story_id")
            if not uses_record and not uses_story:
                continue
            beats = []
            for beat in section.get("beats") or []:
                if not isinstance(beat, dict):
                    continue
                beats.append({
                    **self._pick(
                        beat,
                        "beat_id",
                        "beat_order",
                        "beat_type",
                        "beat_function",
                        "narration_text",
                        "source_record_keys",
                        "support_truth_ids",
                        "visual_goal",
                        "visual_brief",
                    ),
                    "directly_supported_by_record": bool(record_key and record_key in (beat.get("source_record_keys") or [])),
                })
            matched_sections.append({
                **self._pick(
                    section,
                    "section_id",
                    "section_order",
                    "story_id",
                    "story_title",
                    "role",
                    "title_card",
                    "narration_text",
                    "word_count",
                    "estimated_seconds",
                    "used_source_record_keys",
                ),
                "beats": beats,
            })
        section_ids = {section.get("section_id") for section in matched_sections if section.get("section_id")}
        youtube = metadata_data.get("youtube_metadata") if isinstance(metadata_data, dict) else {}
        youtube = youtube if isinstance(youtube, dict) else {}
        metadata_usage = self._metadata_usage(youtube, story_id, section_ids, raw_record.get("url", ""))
        final_youtube = final_metadata_data.get("youtube_metadata") if isinstance(final_metadata_data, dict) else {}
        final_youtube = final_youtube if isinstance(final_youtube, dict) else {}
        final_chapters = [
            chapter for chapter in (final_youtube.get("chapters") or [])
            if isinstance(chapter, dict) and chapter.get("section_id") in section_ids
        ]
        voice_usage = []
        for variant in self.voiceovers(run_id):
            package, _ = self.read_json_rel(run_id, f"voiceover/{variant['variant_id']}/voiceover_package.json")
            package = package if isinstance(package, dict) else {}
            units = [
                self._sanitize_value(unit)
                for unit in package.get("audio_units") or []
                if isinstance(unit, dict) and unit.get("section_id") in section_ids
            ]
            if units:
                voice_usage.append({"variant": variant, "audio_units": units})
        visual = self.visual_scenes(run_id) if story_id else {}
        episode_rendered = bool((visual.get("summary") or {}).get("rendered"))
        stages = [
            self._lineage_step(
                "news_collection",
                "ingestion",
                "produced",
                "The source collector created this raw record and retained source-native metadata.",
                {
                    "source_metadata": self._compact_record(raw_record),
                    "content_length": len(str(raw_record.get("content") or "")),
                    "content_excerpt": self._excerpt(raw_record.get("content")),
                },
                ["news_collection/raw_records.json", "news_collection/candidate_ledger.json"],
            ),
            self._lineage_step(
                "evidence_prep",
                "content",
                "produced" if prepared_record else "stopped",
                "The record was cleaned and normalized." if prepared_record else "The reversible evidence decision stopped this record before semantic review.",
                {
                    "decision": self._sanitize_value(evidence_decision),
                    "prepared_record": self._compact_record(prepared_record),
                    "raw_content_length": len(str(prepared_record.get("raw_content") or "")),
                    "cleaned_content_length": len(str(prepared_record.get("cleaned_content") or "")),
                    "cleaned_excerpt": self._excerpt(prepared_record.get("cleaned_content")),
                },
                ["evidence_prep/decision_ledger.json", "evidence_prep/prepared_records.json"],
            ),
            self._lineage_step(
                "editorial_triage",
                "content",
                "produced" if triage_decision else "not_reached",
                "Semantic editorial judgment was persisted for this record." if triage_decision else "No triage decision references this record.",
                self._sanitize_value(triage_decision),
                ["editorial_triage/decisions.json", "editorial_triage/editorial_triage_result.json"],
            ),
            self._lineage_step(
                "story_mapping",
                "content",
                "produced" if story else "not_reached",
                "The record was assigned to a semantically identified story." if story else "No mapped story contains this record.",
                {
                    "story_id": story_id,
                    "story_title": story.get("story_title", ""),
                    "story_identity": self._sanitize_value(story.get("story_identity") or {}),
                    "event_identity": self._sanitize_value(mapped_record.get("story_mapping_event_identity") or {}),
                    "match_reasons": self._sanitize_value(story.get("match_reasons") or []),
                    "related_stories": self._sanitize_value(story.get("related_stories") or []),
                },
                ["story_mapping/stories.json", "story_mapping/story_mapping_result.json"],
            ),
            self._lineage_step(
                "editorial_selection",
                "content",
                "produced" if selection else "not_reached",
                "The story received a final slate decision." if selection else "No slate decision references the mapped story.",
                self._sanitize_value(selection),
                ["editorial_selection/editorial_slate.json", "editorial_selection/editorial_selection_result.json"],
            ),
            self._lineage_step(
                "video_packaging",
                "content",
                "produced" if packet_story else "not_reached",
                "The selected story was packaged for writing." if packet_story else "Only selected stories enter the video packet.",
                self._summarize_stories([packet_story])[0] if packet_story else {},
                ["video_packaging/video_packet.json", "video_packaging/video_packaging_result.json"],
            ),
            self._lineage_step(
                "script_generation",
                "content",
                "produced" if matched_sections else "not_reached",
                "These script sections and beats use the story or directly cite this source record." if matched_sections else "The script does not reference this record.",
                {"sections": matched_sections},
                ["script_generation/script_package.json", "script_generation/full_script.txt"],
            ),
            self._lineage_step(
                "metadata_creator",
                "content",
                "episode_level" if matched_sections else "not_reached",
                "Publishing metadata is episode-level; these options reference this story or its section.",
                metadata_usage,
                ["metadata_creator/metadata_package.json", "metadata_creator/youtube_metadata.json"],
            ),
            self._lineage_step(
                "voiceover",
                "voiceover",
                "produced" if voice_usage else "not_reached",
                "Voice timing inherits record provenance through the script section.",
                {"variants": voice_usage},
                ["voiceover"],
            ),
            self._lineage_step(
                "metadata_finalizer",
                "voiceover",
                "episode_level" if final_chapters else "not_reached",
                "Final chapters use observed audio timing rather than article-level metadata.",
                {"chapters": self._sanitize_value(final_chapters)},
                ["metadata_finalizer/metadata_package.json", "metadata_finalizer/youtube_metadata.json"],
            ),
            self._lineage_step(
                "visuals",
                "visuals",
                "episode_level" if matched_sections and visual.get("final_video") else "not_reached",
                "The rendered episode is a single motion-graphics video; this record contributes through its script sections and voice timing.",
                {
                    "episode_video": visual.get("final_video", ""),
                    "rendered": episode_rendered,
                    "summary": self._sanitize_value(visual.get("summary") or {}),
                },
                [f"visuals/{run_id}-ad.mp4", "orchestration/visuals_stage_result.json"],
            ),
        ]
        return {
            "run_id": run_id,
            "record": summary,
            "source": self._compact_record(raw_record),
            "stage_count": len(stages),
            "reached_count": sum(step["status"] not in {"not_reached", "missing"} for step in stages),
            "stages": stages,
        }

    def _lineage_step(
        self,
        key: str,
        stage: str,
        status: str,
        explanation: str,
        data: Any,
        raw_paths: list[str],
    ) -> dict[str, Any]:
        definition = MODULE_CATALOG.get(key, {})
        return {
            "key": key,
            "stage": stage,
            "label": definition.get("label", key.replace("_", " ").title()),
            "status": status,
            "purpose": definition.get("purpose", ""),
            "generation": {
                "primary_origin": definition.get("primary_origin", "deterministic"),
                "generation_note": definition.get("generation_note", ""),
                "outputs": definition.get("outputs", []),
            },
            "explanation": explanation,
            "data": self._sanitize_value(data),
            "raw_sources": [
                {"label": Path(path).name.replace("_", " ").title(), "path": path}
                for path in raw_paths
            ],
        }

    def _compact_record(self, record: Any) -> dict[str, Any]:
        if not isinstance(record, dict):
            return {}
        omitted = {"content", "raw_content", "cleaned_content", "metadata"}
        result = {
            key: self._sanitize_value(value)
            for key, value in record.items()
            if key not in omitted and value not in (None, "", [], {})
        }
        metadata = record.get("metadata")
        if isinstance(metadata, dict):
            result["source_metadata"] = self._sanitize_value(metadata)
        return result

    def _metadata_usage(
        self,
        youtube: dict[str, Any],
        story_id: str,
        section_ids: set[str],
        source_url: str,
    ) -> dict[str, Any]:
        def references_story(item: Any) -> bool:
            if not isinstance(item, dict) or not story_id:
                return False
            for key in ("represented_story_ids", "story_ids", "represented_stories"):
                values = item.get(key) or []
                if story_id in values:
                    return True
            return False

        return {
            "scope": "episode_level",
            "article_tags_created": False,
            "tags": self._sanitize_value(youtube.get("tags") or []),
            "source_url_included": bool(source_url and source_url in (youtube.get("source_urls") or [])),
            "title_options": self._sanitize_value([
                item for item in youtube.get("title_options") or [] if references_story(item)
            ]),
            "thumbnail_concepts": self._sanitize_value([
                item for item in youtube.get("thumbnail_concepts") or [] if references_story(item)
            ]),
            "chapters": self._sanitize_value([
                item for item in youtube.get("chapters") or []
                if isinstance(item, dict) and item.get("section_id") in section_ids
            ]),
        }

    def _excerpt(self, value: Any, limit: int = 700) -> str:
        text = self._sanitize_text(str(value or ""))
        return text[:limit] + ("..." if len(text) > limit else "")

    def _summary_metrics(self, run_id: str) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        run_dir = self.run_dir(run_id)
        count_sources = (
            ("collected_record_count", "news_collection/summary.json", ("total_records", "candidate_count")),
            ("prepared_record_count", "evidence_prep/summary.json", ("prepared_record_count",)),
            ("selected_story_count", "editorial_selection/summary.json", ("selected_story_count",)),
        )
        for metric, relative, source_keys in count_sources:
            summary_path = run_dir / relative
            if not summary_path.is_file():
                continue
            summary, _ = self.read_json_file(summary_path)
            if not isinstance(summary, dict):
                continue
            for source_key in source_keys:
                if summary.get(source_key) is not None:
                    metrics[metric] = summary[source_key]
                    break
        script_summary = "script_generation/summary.json"
        script, _ = self.read_json_rel(run_id, script_summary) if (run_dir / script_summary).exists() else ({}, None)
        if isinstance(script, dict):
            metrics["script_word_count"] = script.get("total_word_count")
        voiceovers = self.voiceovers(run_id)
        if voiceovers:
            metrics["selected_voiceover_variant"] = voiceovers[0]["variant_id"]
            metrics["audio_duration_seconds"] = voiceovers[0].get("duration_seconds")
        episode_video = run_dir / "visuals" / f"{run_id}-ad.mp4"
        metrics["final_video_available"] = episode_video.exists()
        return metrics

    def _stage_statuses(self, state: dict[str, Any]) -> dict[str, str]:
        statuses = {}
        stages = state.get("stages") if isinstance(state, dict) else {}
        if isinstance(stages, dict):
            for name in ["ingestion", "content", "voiceover", "visuals"]:
                statuses[name] = (stages.get(name) or {}).get("status", "missing")
        return statuses

    def _overall_status(self, stage_status: dict[str, str], failure_reason: str, errors: Iterable[str | None]) -> str:
        if any(error and error != "Missing" for error in errors):
            return "malformed"
        if failure_reason:
            return "failed"
        values = list(stage_status.values())
        if not values:
            return "partial"
        if any(value == "failed" for value in values):
            return "failed"
        if all(value in {"ok", "ready"} for value in values):
            return "ok"
        return "partial"

    def _last_completed_module(self, state: dict[str, Any]) -> str:
        last = ""
        stages = state.get("stages") if isinstance(state, dict) else {}
        if isinstance(stages, dict):
            for stage in stages.values():
                modules = stage.get("modules") if isinstance(stage, dict) else {}
                if isinstance(modules, dict):
                    for name, info in modules.items():
                        if isinstance(info, dict) and info.get("status") in {"ok", "ready", "partial"}:
                            last = name
        return last

    def _failure_reason(self, state: dict[str, Any], metrics: dict[str, Any]) -> str:
        stages = state.get("stages") if isinstance(state, dict) else {}
        if isinstance(stages, dict):
            for stage in stages.values():
                reason = stage.get("failure_reason") if isinstance(stage, dict) else ""
                if reason:
                    return reason
                modules = stage.get("modules") if isinstance(stage, dict) else {}
                if isinstance(modules, dict):
                    for info in modules.values():
                        summary = info.get("summary") if isinstance(info, dict) else {}
                        if isinstance(summary, dict) and summary.get("failure_reason"):
                            return summary["failure_reason"]
        return ""

    def _created_from_run_id(self, run_id: str) -> str:
        match = re.search(r"run_(\d{4})_(\d{2})_(\d{2})_(\d{6})", run_id)
        if not match:
            return ""
        y, m, d, hms = match.groups()
        return f"{y}-{m}-{d}T{hms[:2]}:{hms[2:4]}:{hms[4:]}"

    def _trim_context(self, context: dict[str, Any]) -> dict[str, Any]:
        return {key: context.get(key) for key in ["run_id", "created_at", "run_profile", "config_environment", "trigger", "pipeline_config_sha256", "pipeline_config_sources", "schema_version"] if key in context}

    def _trim_state(self, state: dict[str, Any]) -> dict[str, Any]:
        stages = {}
        for name, stage in (state.get("stages") or {}).items() if isinstance(state.get("stages"), dict) else []:
            stages[name] = {
                "status": stage.get("status"),
                "started_at": stage.get("started_at"),
                "completed_at": stage.get("completed_at"),
                "invocation_count": stage.get("invocation_count"),
                "module_order": stage.get("module_order"),
                "failure_reason": stage.get("failure_reason"),
            }
        return {"run_id": state.get("run_id"), "updated_at": state.get("updated_at"), "stages": stages}

    def _module_artifacts(self, module_dir: Path, rel: str, deep: bool = False) -> list[dict[str, Any]]:
        if not module_dir.exists():
            return []
        max_depth = 4 if deep else 1
        return self._tree_for_dir(module_dir, module_dir, max_depth=max_depth, prefix=rel)

    def _tree_for_dir(self, root: Path, base: Path, max_depth: int, prefix: str = "") -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        if max_depth < 0 or not root.exists():
            return nodes
        try:
            children = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            return nodes
        for child in children:
            name = child.name
            if name.startswith("."):
                continue
            rel = child.relative_to(base).as_posix()
            full_rel = f"{prefix}/{rel}" if prefix else rel
            try:
                self._ensure_not_denied(full_rel)
                resolved = child.resolve()
                resolved.relative_to(self.output_root)
            except Exception:
                continue
            stat = child.stat()
            node = {
                "name": name,
                "path": full_rel,
                "type": "directory" if child.is_dir() else "file",
                "size": stat.st_size if child.is_file() else None,
                "mtime": stat.st_mtime,
            }
            if child.is_file():
                node["extension"] = child.suffix.lower()
                node["media"] = child.suffix.lower() in MEDIA_EXTENSIONS
            if child.is_dir() and max_depth > 0:
                node["children"] = self._tree_for_dir(child, base, max_depth - 1, prefix=prefix)
            nodes.append(node)
        return nodes

    def _top_level_module_dirs(self, run_dir: Path) -> list[str]:
        ignore = {"inputs", "orchestration", "handoffs", "voiceover", "visuals"}
        return [p.name for p in sorted(run_dir.iterdir()) if p.is_dir() and p.name not in ignore]

    def _pick(self, data: Any, *keys: str) -> dict[str, Any]:
        if not isinstance(data, dict):
            return {}
        return {key: self._sanitize_value(data.get(key)) for key in keys if data.get(key) is not None}

    def _summary_preview(self, summary: Any, limit: int = 16) -> dict[str, Any]:
        if not isinstance(summary, dict):
            return {}
        preview: dict[str, Any] = {}
        skipped = {"run_id", "generated_at", "status", "output_dir"}
        for key, value in summary.items():
            if len(preview) >= limit:
                break
            if key in skipped or key.endswith("_path") or key.endswith("_sha256"):
                continue
            if isinstance(value, str) and not value.strip():
                continue
            if value is None or isinstance(value, (str, int, float, bool)):
                preview[key] = self._sanitize_value(value)
            elif isinstance(value, dict) and len(value) <= 12 and all(
                child is None or isinstance(child, (str, int, float, bool))
                for child in value.values()
            ):
                preview[key] = self._sanitize_value(value)
        return preview

    def _named_rows(self, values: Any) -> list[dict[str, Any]]:
        if not isinstance(values, dict):
            return []
        return [
            {"name": name, **self._summary_preview(value, limit=24)}
            for name, value in values.items()
            if isinstance(value, dict)
        ]

    def _summarize_source_groups(self, groups: Any) -> list[dict[str, Any]]:
        if not isinstance(groups, dict):
            return []
        result = []
        for name, group in groups.items():
            if not isinstance(group, dict):
                continue
            sources = []
            for source_name, source in (group.get("sources") or {}).items():
                if not isinstance(source, dict):
                    continue
                notes = [self._sanitize_text(str(note)) for note in (source.get("notes") or [])]
                sources.append({
                    "name": source_name,
                    "status": source.get("status", "unknown"),
                    "fetched_count": source.get("fetched_count", 0),
                    "collected_count": source.get("collected_count", 0),
                    "filtered_out_count": source.get("filtered_out_count", 0),
                    "notes": notes,
                })
            result.append({
                "name": name,
                "collector": group.get("collector", ""),
                "status": group.get("status", "unknown"),
                "fetched_count": group.get("fetched_count", 0),
                "collected_count": group.get("collected_count", 0),
                "filtered_out_count": group.get("filtered_out_count", 0),
                "source_count": len(sources),
                "failed_source_count": sum(source["status"] == "failed" for source in sources),
                "sources": sources,
            })
        return result

    def _summarize_records(self, records: Any) -> list[dict[str, Any]]:
        if not isinstance(records, list):
            return []
        result = []
        for record in records:
            if not isinstance(record, dict):
                continue
            excerpt = record.get("summary") or record.get("cleaned_content") or record.get("content") or ""
            excerpt = self._sanitize_text(str(excerpt))
            result.append({
                "record_key": record.get("record_key") or record.get("record_id") or record.get("candidate_key", ""),
                "title": record.get("title", ""),
                "url": record.get("url", ""),
                "source": record.get("source_name") or record.get("source", ""),
                "source_group": record.get("source_group", ""),
                "source_relationship": record.get("source_relationship", ""),
                "published_at": record.get("published_at", ""),
                "content_status": record.get("content_status", ""),
                "trust_tier": record.get("trust_tier"),
                "excerpt": excerpt[:500] + ("..." if len(excerpt) > 500 else ""),
            })
        return result

    def _summarize_evidence_decisions(self, decisions: Any) -> list[dict[str, Any]]:
        if not isinstance(decisions, list):
            return []
        fields = (
            "record_id",
            "record_key",
            "title",
            "source",
            "source_group",
            "decision",
            "reason_codes",
            "decision_owner",
        )
        return [self._pick(decision, *fields) for decision in decisions if isinstance(decision, dict)]

    def _summarize_triage_decisions(
        self,
        decisions: Any,
        record_index: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not isinstance(decisions, list):
            return []
        result = []
        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            record = record_index.get(decision.get("record_key"), {})
            result.append({
                "record_key": decision.get("record_key", ""),
                "title": record.get("title", ""),
                "source": record.get("source_name") or record.get("source", ""),
                "url": record.get("url", ""),
                "recommended_action": decision.get("recommended_action", ""),
                "reason": self._sanitize_text(str(decision.get("reason", ""))),
                "confidence": decision.get("confidence"),
                "topic_relevance": decision.get("topic_relevance", ""),
                "newsworthiness": decision.get("newsworthiness", ""),
                "audience_value": decision.get("audience_value", ""),
                "content_usability": decision.get("content_usability", ""),
                "likely_content_type": decision.get("likely_content_type", ""),
                "novelty": decision.get("novelty", ""),
                "possible_story_keys": self._sanitize_value(decision.get("possible_story_keys") or []),
            })
        return result

    def _summarize_rejections(
        self,
        rejections: Any,
        story_index: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not isinstance(rejections, list):
            return []
        result = []
        for rejection in rejections:
            if not isinstance(rejection, dict):
                continue
            story = story_index.get(rejection.get("story_id"), {})
            result.append({
                "story_id": rejection.get("story_id", ""),
                "story_title": story.get("story_title", ""),
                "reason": self._sanitize_text(str(rejection.get("reason", ""))),
                "confidence": rejection.get("confidence"),
                "selection_stage": rejection.get("selection_stage", ""),
            })
        return result

    def _summarize_stories(self, stories: list[Any]) -> list[dict[str, Any]]:
        result = []
        for story in stories:
            if not isinstance(story, dict):
                continue
            identity = story.get("story_identity") if isinstance(story.get("story_identity"), dict) else {}
            selection = story.get("editorial_selection") if isinstance(story.get("editorial_selection"), dict) else {}
            result.append({
                "story_id": story.get("story_id", ""),
                "story_title": story.get("story_title", ""),
                "role": selection.get("role") or story.get("story_role", ""),
                "action": selection.get("action", ""),
                "selection_order": selection.get("selection_order"),
                "selection_reason": self._sanitize_text(str(selection.get("selection_reason") or selection.get("reason") or "")),
                "viewer_payoff": self._sanitize_text(str(selection.get("viewer_payoff", ""))),
                "confidence": selection.get("confidence"),
                "record_count": story.get("record_count") or len(story.get("records") or []),
                "source_groups": story.get("source_groups") or [],
                "why_it_matters": self._sanitize_text(str(identity.get("why_it_matters", ""))),
                "one_sentence_story": self._sanitize_text(str(identity.get("one_sentence_story", ""))),
                "primary_entity": identity.get("primary_entity", ""),
                "owning_org": identity.get("owning_org", ""),
                "product_or_project": identity.get("product_or_project", ""),
                "story_type": identity.get("story_type") or story.get("story_type_hint", ""),
                "editorial_value": identity.get("editorial_value", ""),
                "related_story_count": len(story.get("related_stories") or []),
                "records": [
                    {
                        "record_key": record.get("record_key", ""),
                        "title": record.get("title", ""),
                        "source": record.get("source_name") or record.get("source", ""),
                        "url": record.get("url", ""),
                        "relationship": record.get("source_relationship", ""),
                        "published_at": record.get("published_at", ""),
                        "content_status": record.get("content_status", ""),
                        "summary": self._sanitize_text(str(record.get("summary", ""))),
                    }
                    for record in (story.get("records") or [])
                    if isinstance(record, dict)
                ],
            })
        return result

    def _ledger_row(self, record: dict[str, Any], index: int, include_payload: bool) -> dict[str, Any]:
        heavy_keys = {"messages", "prompt", "response_text", "raw_response", "parsed_output", "structured_response", "parsing_diagnostics", "complete_prompt"}
        summary = {key: self._sanitize_value(value) for key, value in record.items() if include_payload or key not in heavy_keys}
        if not include_payload:
            summary["has_payload"] = any(key in record for key in heavy_keys)
        summary["index"] = index
        return summary

    def _read_tail_lines(self, path: Path, tail: int) -> list[str]:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
        return [line.rstrip("\n") for line in lines[-tail:]]

    def _sanitize_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._sanitize_text(value)
        if isinstance(value, list):
            return [self._sanitize_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._sanitize_value(child) for key, child in value.items()}
        return value

    def _sanitize_text(self, text: str) -> str:
        if not text:
            return text
        project = self.project_root.as_posix()
        replacements = {
            f"{project}/output/": "output/",
            f"{project}/src/pipeline/config/": "src/pipeline/config/",
            f"{project}/": "[project]/",
        }
        sanitized = text
        for old, new in replacements.items():
            sanitized = sanitized.replace(old, new)

        def replace_absolute(match: re.Match[str]) -> str:
            value = match.group(0)
            if value.startswith("output/") or value.startswith("src/pipeline/config/"):
                return value
            return "[redacted-absolute-path]"

        return ABSOLUTE_PATH_RE.sub(replace_absolute, sanitized)

    def _walk(self, value: Any, path: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], Any]]:
        yield path, value
        if isinstance(value, dict):
            for key, child in value.items():
                yield from self._walk(child, path + (str(key),))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from self._walk(child, path + (str(index),))
