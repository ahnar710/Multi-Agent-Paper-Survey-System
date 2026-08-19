"""Small SQLite repository used by the local and Docker deployments."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from paper_agents.state_machine import ensure_transition
from paper_agents.schemas import (
    ResearchRun,
    RunStatus,
    WorkItem,
    WorkItemStatus,
)


class ResearchStore:
    """Persist workflow state without requiring an external database server."""

    def __init__(self, path: Path | str = Path("data/research.db")) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS research_runs (
                    run_id TEXT PRIMARY KEY,
                    topic_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    status TEXT NOT NULL,
                    candidate_count INTEGER NOT NULL DEFAULT 0,
                    included_count INTEGER NOT NULL DEFAULT 0,
                    verified_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error TEXT
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    run_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, kind, entity_id),
                    FOREIGN KEY (run_id) REFERENCES research_runs(run_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_artifacts_run_kind
                ON artifacts(run_id, kind);

                CREATE TABLE IF NOT EXISTS work_items (
                    work_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 2,
                    available_at TEXT NOT NULL,
                    lease_until TEXT,
                    worker_id TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(run_id, stage, entity_id),
                    FOREIGN KEY (run_id) REFERENCES research_runs(run_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_work_claim
                ON work_items(stage, status, available_at, lease_until);
                """
            )

    def create_run(self, run: ResearchRun) -> None:
        values = run.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO research_runs (
                    run_id, topic_id, question, status,
                    candidate_count, included_count, verified_count, failed_count,
                    created_at, updated_at, error
                ) VALUES (
                    :run_id, :topic_id, :question, :status,
                    :candidate_count, :included_count, :verified_count, :failed_count,
                    :created_at, :updated_at, :error
                )
                """,
                values,
            )

    def get_run(self, run_id: str) -> ResearchRun | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM research_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return ResearchRun.model_validate(dict(row)) if row else None

    def list_runs(self, limit: int = 20) -> list[ResearchRun]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM research_runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [ResearchRun.model_validate(dict(row)) for row in rows]

    def update_run(
        self,
        run_id: str,
        *,
        status: RunStatus | None = None,
        candidate_count: int | None = None,
        included_count: int | None = None,
        verified_count: int | None = None,
        failed_count: int | None = None,
        error: str | None = None,
    ) -> ResearchRun:
        current = self.get_run(run_id)
        if current is None:
            raise KeyError(f"任务不存在: {run_id}")
        if status is not None:
            ensure_transition(current.status, status)
        updates: dict[str, Any] = {
            "updated_at": datetime.now(timezone.utc),
            "error": error,
        }
        for key, value in (
            ("status", status),
            ("candidate_count", candidate_count),
            ("included_count", included_count),
            ("verified_count", verified_count),
            ("failed_count", failed_count),
        ):
            if value is not None:
                updates[key] = value

        updated = current.model_copy(update=updates)
        values = updated.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE research_runs SET
                    status=:status,
                    candidate_count=:candidate_count,
                    included_count=:included_count,
                    verified_count=:verified_count,
                    failed_count=:failed_count,
                    updated_at=:updated_at,
                    error=:error
                WHERE run_id=:run_id
                """,
                values,
            )
        return updated

    def put_artifact(
        self, run_id: str, kind: str, entity_id: str, payload: dict[str, Any]
    ) -> None:
        if self.get_run(run_id) is None:
            raise KeyError(f"任务不存在: {run_id}")
        now = datetime.now(timezone.utc).isoformat()
        serialized = json.dumps(payload, ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO artifacts (
                    run_id, kind, entity_id, payload, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, kind, entity_id) DO UPDATE SET
                    payload=excluded.payload,
                    updated_at=excluded.updated_at
                """,
                (run_id, kind, entity_id, serialized, now, now),
            )

    def get_artifact(
        self, run_id: str, kind: str, entity_id: str
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload FROM artifacts
                WHERE run_id = ? AND kind = ? AND entity_id = ?
                """,
                (run_id, kind, entity_id),
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def list_artifacts(self, run_id: str, kind: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM artifacts
                WHERE run_id = ? AND kind = ? ORDER BY entity_id
                """,
                (run_id, kind),
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    @staticmethod
    def _work_item(row: sqlite3.Row) -> WorkItem:
        payload = dict(row)
        payload["payload"] = json.loads(payload["payload"])
        return WorkItem.model_validate(payload)

    def enqueue_work(
        self,
        run_id: str,
        *,
        stage: str,
        entity_id: str,
        payload: dict[str, Any],
        max_attempts: int = 2,
    ) -> WorkItem:
        if self.get_run(run_id) is None:
            raise KeyError(f"任务不存在: {run_id}")
        now = datetime.now(timezone.utc)
        work = WorkItem(
            work_id="work-" + uuid4().hex[:16],
            run_id=run_id,
            stage=stage,
            entity_id=entity_id,
            payload=payload,
            available_at=now,
            created_at=now,
            updated_at=now,
            max_attempts=max_attempts,
        )
        values = work.model_dump(mode="json")
        values["payload"] = json.dumps(payload, ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO work_items (
                    work_id, run_id, stage, entity_id, status, payload,
                    attempt, max_attempts, available_at, lease_until,
                    worker_id, error, created_at, updated_at
                ) VALUES (
                    :work_id, :run_id, :stage, :entity_id, :status, :payload,
                    :attempt, :max_attempts, :available_at, :lease_until,
                    :worker_id, :error, :created_at, :updated_at
                )
                ON CONFLICT(run_id, stage, entity_id) DO NOTHING
                """,
                values,
            )
            row = connection.execute(
                """
                SELECT * FROM work_items
                WHERE run_id=? AND stage=? AND entity_id=?
                """,
                (run_id, stage, entity_id),
            ).fetchone()
        assert row is not None
        return self._work_item(row)

    def claim_work(
        self,
        *,
        stage: str,
        worker_id: str,
        lease_seconds: int = 300,
        run_id: str | None = None,
    ) -> WorkItem | None:
        if lease_seconds < 1:
            raise ValueError("lease_seconds 必须大于 0")
        now = datetime.now(timezone.utc)
        lease_until = now + timedelta(seconds=lease_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            query = """
                SELECT * FROM work_items
                WHERE stage=? AND status=? AND available_at<=?
            """
            params: list[Any] = [
                stage,
                WorkItemStatus.PENDING.value,
                now.isoformat(),
            ]
            if run_id is not None:
                query += " AND run_id=?"
                params.append(run_id)
            query += " ORDER BY created_at, work_id LIMIT 1"
            row = connection.execute(query, params).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                UPDATE work_items SET
                    status=?, attempt=attempt+1, worker_id=?, lease_until=?,
                    updated_at=?, error=NULL
                WHERE work_id=? AND status=?
                """,
                (
                    WorkItemStatus.RUNNING.value,
                    worker_id,
                    lease_until.isoformat(),
                    now.isoformat(),
                    row["work_id"],
                    WorkItemStatus.PENDING.value,
                ),
            )
            claimed = connection.execute(
                "SELECT * FROM work_items WHERE work_id=?", (row["work_id"],)
            ).fetchone()
        return self._work_item(claimed) if claimed else None

    def complete_work(self, work_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            changed = connection.execute(
                """
                UPDATE work_items SET status=?, lease_until=NULL, updated_at=?
                WHERE work_id=? AND status=?
                """,
                (
                    WorkItemStatus.COMPLETED.value,
                    now,
                    work_id,
                    WorkItemStatus.RUNNING.value,
                ),
            ).rowcount
        if changed != 1:
            raise KeyError(f"不存在可完成的 running work item: {work_id}")

    def fail_work(
        self, work_id: str, error: str, *, retry_delay_seconds: int = 0
    ) -> WorkItem:
        now = datetime.now(timezone.utc)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM work_items WHERE work_id=?", (work_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"工作项不存在: {work_id}")
            retry = int(row["attempt"]) < int(row["max_attempts"])
            status = WorkItemStatus.PENDING if retry else WorkItemStatus.FAILED
            available = now + timedelta(seconds=max(0, retry_delay_seconds))
            connection.execute(
                """
                UPDATE work_items SET
                    status=?, available_at=?, lease_until=NULL, worker_id=NULL,
                    error=?, updated_at=?
                WHERE work_id=?
                """,
                (
                    status.value,
                    available.isoformat(),
                    error,
                    now.isoformat(),
                    work_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM work_items WHERE work_id=?", (work_id,)
            ).fetchone()
        assert updated is not None
        return self._work_item(updated)

    def recover_expired_leases(self) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            changed = connection.execute(
                """
                UPDATE work_items SET
                    status=?, worker_id=NULL, lease_until=NULL,
                    available_at=?, updated_at=?, error='worker lease expired'
                WHERE status=? AND lease_until IS NOT NULL AND lease_until<?
                """,
                (
                    WorkItemStatus.PENDING.value,
                    now,
                    now,
                    WorkItemStatus.RUNNING.value,
                    now,
                ),
            ).rowcount
        return changed

    def list_work(self, run_id: str, stage: str | None = None) -> list[WorkItem]:
        query = "SELECT * FROM work_items WHERE run_id=?"
        params: tuple[Any, ...] = (run_id,)
        if stage is not None:
            query += " AND stage=?"
            params += (stage,)
        query += " ORDER BY created_at, work_id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._work_item(row) for row in rows]
