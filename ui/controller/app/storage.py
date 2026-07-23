from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any


ACTIVE_JOB_STATUSES = ("queued", "running", "cancelling", "orphaned")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class ControllerStore:
    def __init__(self, state_root: Path) -> None:
        self.state_root = state_root.resolve()
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_root / "run_desk.sqlite3"
        self.lock_path = self.state_root / "pipeline.lock"
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    operation TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    commands_json TEXT NOT NULL,
                    current_step INTEGER NOT NULL DEFAULT 0,
                    step_count INTEGER NOT NULL,
                    current_stage TEXT NOT NULL DEFAULT '',
                    pid INTEGER,
                    exit_code INTEGER,
                    failure_reason TEXT NOT NULL DEFAULT '',
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    stream TEXT NOT NULL,
                    line TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS job_events_job_id_id
                    ON job_events(job_id, id);

                CREATE TABLE IF NOT EXISTS review_notes (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS config_revisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL,
                    before_sha256 TEXT NOT NULL,
                    after_sha256 TEXT NOT NULL,
                    before_text TEXT NOT NULL,
                    after_text TEXT NOT NULL,
                    change_summary TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS config_revisions_path_id
                    ON config_revisions(path, id DESC);
                """
            )

    def create_job(
        self,
        *,
        job_id: str,
        request_id: str,
        operation: str,
        run_id: str,
        plan: dict[str, Any],
        commands: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], bool]:
        created_at = now_iso()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO jobs (
                        id, request_id, operation, run_id, status, plan_json,
                        commands_json, step_count, created_at
                    ) VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        request_id,
                        operation,
                        run_id,
                        json.dumps(plan, separators=(",", ":")),
                        json.dumps(commands, separators=(",", ":")),
                        len(commands),
                        created_at,
                    ),
                )
        except sqlite3.IntegrityError:
            existing = self.get_job_by_request(request_id)
            if existing is None:
                raise
            return existing, False
        job = self.get_job(job_id)
        assert job is not None
        return job, True

    def update_job(self, job_id: str, **fields: Any) -> None:
        allowed = {
            "status",
            "current_step",
            "current_stage",
            "pid",
            "exit_code",
            "failure_reason",
            "cancel_requested",
            "started_at",
            "finished_at",
        }
        values = {key: value for key, value in fields.items() if key in allowed}
        if not values:
            return
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ?",
                (*values.values(), job_id),
            )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job(row) if row else None

    def get_job_by_request(self, request_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        return self._job(row) if row else None

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [self._job(row) for row in rows]

    def active_job(self) -> dict[str, Any] | None:
        placeholders = ",".join("?" for _ in ACTIVE_JOB_STATUSES)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM jobs
                WHERE status IN ({placeholders})
                ORDER BY created_at DESC
                LIMIT 1
                """,
                ACTIVE_JOB_STATUSES,
            ).fetchone()
        return self._job(row) if row else None

    def unfinished_jobs(self) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in ACTIVE_JOB_STATUSES)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM jobs WHERE status IN ({placeholders})",
                ACTIVE_JOB_STATUSES,
            ).fetchall()
        return [self._job(row) for row in rows]

    def append_event(self, job_id: str, stream: str, line: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO job_events (job_id, created_at, stream, line)
                VALUES (?, ?, ?, ?)
                """,
                (job_id, now_iso(), stream, line[:4000]),
            )
            return int(cursor.lastrowid)

    def events(self, job_id: str, *, after: int = 0, limit: int = 500) -> dict[str, Any]:
        limit = max(1, min(limit, 1000))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, created_at, stream, line
                FROM job_events
                WHERE job_id = ? AND id > ?
                ORDER BY id
                LIMIT ?
                """,
                (job_id, max(0, after), limit),
            ).fetchall()
        events = [dict(row) for row in rows]
        return {
            "events": events,
            "next_after": events[-1]["id"] if events else after,
        }

    def event_count(self, job_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM job_events WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return int(row["count"]) if row else 0

    def get_note(self, run_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM review_notes WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row:
            return dict(row)
        return {
            "run_id": run_id,
            "status": "open",
            "body": "",
            "created_at": None,
            "updated_at": None,
        }

    def save_note(self, run_id: str, *, status: str, body: str) -> dict[str, Any]:
        timestamp = now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO review_notes (run_id, status, body, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status = excluded.status,
                    body = excluded.body,
                    updated_at = excluded.updated_at
                """,
                (run_id, status, body, timestamp, timestamp),
            )
        return self.get_note(run_id)

    def save_config_revision(
        self,
        *,
        path: str,
        before_sha256: str,
        after_sha256: str,
        before_text: str,
        after_text: str,
        change_summary: str,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO config_revisions (
                    path, before_sha256, after_sha256, before_text, after_text,
                    change_summary, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    path,
                    before_sha256,
                    after_sha256,
                    before_text,
                    after_text,
                    change_summary,
                    now_iso(),
                ),
            )
            return int(cursor.lastrowid)

    def config_revisions(self, path: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        with self._connect() as connection:
            if path:
                rows = connection.execute(
                    """
                    SELECT id, path, before_sha256, after_sha256, change_summary, created_at
                    FROM config_revisions
                    WHERE path = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (path, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT id, path, before_sha256, after_sha256, change_summary, created_at
                    FROM config_revisions
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _job(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["plan"] = json.loads(result.pop("plan_json"))
        result["commands"] = json.loads(result.pop("commands_json"))
        result["cancel_requested"] = bool(result["cancel_requested"])
        return result
