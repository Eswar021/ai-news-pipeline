from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .catalog import catalog_payload
from .repository import MEDIA_EXTENSIONS, RepositoryError, SafeRepository


def create_app(project_root: Path | None = None) -> FastAPI:
    repo = SafeRepository(project_root)
    app = FastAPI(title="AI Content Creation Run Inspector", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.state.repo = repo

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "bind": "127.0.0.1"}

    @app.get("/api/catalog")
    def catalog() -> dict[str, object]:
        return catalog_payload()

    @app.get("/api/runs")
    def runs() -> dict[str, object]:
        return {"runs": repo.list_runs()}

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str) -> dict[str, object]:
        try:
            return repo.run_detail(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        except RepositoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/state")
    def run_state(run_id: str) -> dict[str, object]:
        try:
            state, error = repo.read_json_rel(run_id, "orchestration/run_state.json")
            return {"state": state, "error": error}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        except RepositoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/modules/{module:path}")
    def module_detail(run_id: str, module: str) -> dict[str, object]:
        try:
            return repo.module_detail(run_id, module)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run or module not found") from exc
        except RepositoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/workflow")
    def workflow(run_id: str) -> dict[str, object]:
        try:
            return repo.workflow(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        except RepositoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/records")
    def records(
        run_id: str,
        search: str = "",
        outcome: str = "all",
        offset: int = Query(0, ge=0),
        limit: int = Query(30, ge=1, le=100),
    ) -> dict[str, object]:
        try:
            return repo.record_page(
                run_id,
                search=search,
                outcome=outcome,
                offset=offset,
                limit=limit,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        except RepositoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/records/{record_ref}")
    def record_lineage(run_id: str, record_ref: str) -> dict[str, object]:
        try:
            return repo.record_lineage(run_id, record_ref)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Record not found") from exc
        except RepositoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/artifacts")
    def artifact(run_id: str, path: str = Query(...), max_bytes: int = Query(2_000_000, ge=1, le=8_000_000)) -> dict[str, object]:
        try:
            return repo.artifact_content(run_id, path, max_bytes=max_bytes)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Artifact not found") from exc
        except RepositoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/artifact-tree")
    def artifact_tree(run_id: str) -> dict[str, object]:
        try:
            repo.run_dir(run_id)
            return {"tree": repo.artifact_tree(run_id)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        except RepositoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/logs/{stage}")
    def logs(
        run_id: str,
        stage: str,
        search: str = "",
        severity: str = "",
        tail: int = Query(500, ge=1, le=5000),
    ) -> dict[str, object]:
        try:
            return repo.log_content(run_id, stage, search=search, severity=severity, tail=tail)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Log not found") from exc
        except RepositoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/llm-calls/{module:path}/records/{index}")
    def llm_call_record(run_id: str, module: str, index: int) -> dict[str, object]:
        try:
            return repo.jsonl_record(run_id, module, index=index)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="LLM call not found") from exc
        except RepositoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/llm-calls/{module:path}")
    def llm_calls(
        run_id: str,
        module: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(25, ge=1, le=100),
    ) -> dict[str, object]:
        try:
            return repo.jsonl_page(run_id, module, offset=offset, limit=limit)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="LLM ledger not found") from exc
        except RepositoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/tts-calls/{variant_id}")
    def tts_calls(
        run_id: str,
        variant_id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(25, ge=1, le=100),
    ) -> dict[str, object]:
        try:
            return repo.jsonl_page(run_id, variant_id, ledger="tts", offset=offset, limit=limit)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="TTS ledger not found") from exc
        except RepositoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/tts-calls/{variant_id}/records/{index}")
    def tts_call_record(run_id: str, variant_id: str, index: int) -> dict[str, object]:
        try:
            return repo.jsonl_record(run_id, variant_id, index=index, ledger="tts")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="TTS request not found") from exc
        except RepositoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/voiceovers")
    def voiceovers(run_id: str) -> dict[str, object]:
        try:
            return {"voiceovers": repo.voiceovers(run_id)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        except RepositoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/voiceovers/{variant_id}")
    def voiceover_detail(run_id: str, variant_id: str) -> dict[str, object]:
        try:
            return repo.voiceover_detail(run_id, variant_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Voiceover package not found") from exc
        except RepositoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/visual-scenes")
    def visual_scenes(run_id: str) -> dict[str, object]:
        try:
            return repo.visual_scenes(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        except RepositoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/compare/runs")
    def compare_runs(left: str = Query(...), right: str = Query(...)) -> dict[str, object]:
        try:
            return repo.compare_runs(left, right)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        except RepositoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/provenance/llm/{module}")
    def llm_provenance(
        run_id: str,
        module: str,
        record_key: str = "",
        story_id: str = "",
        section_id: str = "",
        limit: int = Query(50, ge=1, le=200),
    ) -> dict[str, object]:
        try:
            return repo.llm_provenance(
                run_id,
                module,
                record_key=record_key,
                story_id=story_id,
                section_id=section_id,
                limit=limit,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="LLM ledger not found") from exc
        except RepositoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/config/manifest")
    def config_manifest() -> dict[str, object]:
        return repo.config_manifest()

    @app.get("/api/config/source")
    def config_source(path: str = Query(...)) -> dict[str, object]:
        try:
            return repo.config_source(path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Config file not found") from exc
        except RepositoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/config")
    def run_config(run_id: str) -> dict[str, object]:
        try:
            return repo.run_config(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        except RepositoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/media")
    def media(request: Request, path: str = Query(...)) -> Response:
        try:
            resolved = repo.resolve_allowlisted(path)
            if not resolved.path.is_file():
                raise FileNotFoundError(path)
            if resolved.path.suffix.lower() not in MEDIA_EXTENSIONS and resolved.path.suffix.lower() not in {".vtt", ".srt"}:
                raise RepositoryError("File type is not streamable")
            return _range_response(request, resolved.path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Media not found") from exc
        except RepositoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


def _range_response(request: Request, path: Path) -> Response:
    file_size = path.stat().st_size
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    range_header = request.headers.get("range")
    headers = {"Accept-Ranges": "bytes", "Content-Type": content_type}
    if not range_header:
        headers["Content-Length"] = str(file_size)
        return StreamingResponse(_file_iterator(path, 0, file_size - 1), media_type=content_type, headers=headers)
    start, end = _parse_range(range_header, file_size)
    if start >= file_size or end >= file_size or start > end:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
    headers.update({
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Length": str(end - start + 1),
    })
    return StreamingResponse(_file_iterator(path, start, end), status_code=206, media_type=content_type, headers=headers)


def _parse_range(header: str, file_size: int) -> tuple[int, int]:
    if not header.startswith("bytes="):
        return 0, file_size - 1
    spec = header.removeprefix("bytes=").split(",", 1)[0].strip()
    start_text, _, end_text = spec.partition("-")
    if start_text == "":
        suffix = int(end_text or "0")
        return max(0, file_size - suffix), file_size - 1
    start = int(start_text)
    end = int(end_text) if end_text else file_size - 1
    return start, min(end, file_size - 1)


def _file_iterator(path: Path, start: int, end: int, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = handle.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


app = create_app()
