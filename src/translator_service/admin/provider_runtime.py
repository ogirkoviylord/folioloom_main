from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class AIProviderRuntimeChannel:
    label: str
    weight: int
    max_parallel_requests: int


@dataclass(frozen=True)
class AIProviderRuntimeStatus:
    provider_id: str
    source: str
    status: str
    reload_interval_seconds: float
    last_reloaded_at: datetime
    active_channels: tuple[AIProviderRuntimeChannel, ...]
    error: str | None = None


@dataclass(frozen=True)
class AIProviderRuntimeReloadRequest:
    request_id: str
    provider_id: str
    actor_id: str
    requested_at: datetime
    consumed_at: datetime | None = None

    @property
    def pending(self) -> bool:
        return self.consumed_at is None


class SQLiteAIProviderRuntimeStore:
    def __init__(self, db_path: str | Path) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._create_schema()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SQLiteAIProviderRuntimeStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def record_status(
        self,
        *,
        provider_id: str,
        source: str,
        status: str,
        reload_interval_seconds: float,
        active_channels: tuple[AIProviderRuntimeChannel, ...],
        error: str | None,
    ) -> AIProviderRuntimeStatus:
        now = datetime.now(UTC)
        payload = json.dumps(
            [
                {
                    "label": channel.label,
                    "weight": max(1, int(channel.weight)),
                    "max_parallel_requests": max(
                        1,
                        int(channel.max_parallel_requests),
                    ),
                }
                for channel in active_channels
            ],
            sort_keys=True,
        )
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO admin_ai_provider_runtime_status (
                    provider_id, source, status, reload_interval_seconds,
                    active_channels_json, error, last_reloaded_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_id) DO UPDATE SET
                    source = excluded.source,
                    status = excluded.status,
                    reload_interval_seconds = excluded.reload_interval_seconds,
                    active_channels_json = excluded.active_channels_json,
                    error = excluded.error,
                    last_reloaded_at = excluded.last_reloaded_at
                """,
                (
                    provider_id,
                    source,
                    status,
                    max(0.0, float(reload_interval_seconds)),
                    payload,
                    error,
                    now.isoformat(),
                ),
            )
        status_summary = self.get_status(provider_id)
        if status_summary is None:
            raise RuntimeError("Runtime status was not recorded")
        return status_summary

    def get_status(self, provider_id: str) -> AIProviderRuntimeStatus | None:
        row = self._connection.execute(
            """
            SELECT *
            FROM admin_ai_provider_runtime_status
            WHERE provider_id = ?
            """,
            (provider_id,),
        ).fetchone()
        if row is None:
            return None
        return _status_from_row(row)

    def request_reload(
        self,
        *,
        provider_id: str,
        actor_id: str,
    ) -> AIProviderRuntimeReloadRequest:
        request = AIProviderRuntimeReloadRequest(
            request_id=uuid4().hex,
            provider_id=provider_id,
            actor_id=actor_id,
            requested_at=datetime.now(UTC),
        )
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO admin_ai_provider_runtime_reload_requests (
                    request_id, provider_id, actor_id, requested_at, consumed_at
                )
                VALUES (?, ?, ?, ?, NULL)
                """,
                (
                    request.request_id,
                    request.provider_id,
                    request.actor_id,
                    request.requested_at.isoformat(),
                ),
            )
        return request

    def consume_reload_request(
        self,
        provider_id: str,
    ) -> AIProviderRuntimeReloadRequest | None:
        row = self._connection.execute(
            """
            SELECT *
            FROM admin_ai_provider_runtime_reload_requests
            WHERE provider_id = ? AND consumed_at IS NULL
            ORDER BY datetime(requested_at), rowid
            LIMIT 1
            """,
            (provider_id,),
        ).fetchone()
        if row is None:
            return None
        now = datetime.now(UTC)
        with self._connection:
            self._connection.execute(
                """
                UPDATE admin_ai_provider_runtime_reload_requests
                SET consumed_at = ?
                WHERE request_id = ?
                """,
                (now.isoformat(), row["request_id"]),
            )
        return AIProviderRuntimeReloadRequest(
            request_id=row["request_id"],
            provider_id=row["provider_id"],
            actor_id=row["actor_id"],
            requested_at=datetime.fromisoformat(row["requested_at"]),
            consumed_at=now,
        )

    def get_reload_state(
        self,
        provider_id: str,
    ) -> AIProviderRuntimeReloadRequest | None:
        row = self._connection.execute(
            """
            SELECT *
            FROM admin_ai_provider_runtime_reload_requests
            WHERE provider_id = ?
            ORDER BY datetime(requested_at) DESC, rowid DESC
            LIMIT 1
            """,
            (provider_id,),
        ).fetchone()
        if row is None:
            return None
        consumed_at = row["consumed_at"]
        return AIProviderRuntimeReloadRequest(
            request_id=row["request_id"],
            provider_id=row["provider_id"],
            actor_id=row["actor_id"],
            requested_at=datetime.fromisoformat(row["requested_at"]),
            consumed_at=(
                datetime.fromisoformat(consumed_at) if consumed_at is not None else None
            ),
        )

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_ai_provider_runtime_status (
                    provider_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reload_interval_seconds REAL NOT NULL,
                    active_channels_json TEXT NOT NULL,
                    error TEXT,
                    last_reloaded_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_ai_provider_runtime_reload_requests (
                    request_id TEXT PRIMARY KEY,
                    provider_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    consumed_at TEXT
                )
                """
            )


def _status_from_row(row: sqlite3.Row) -> AIProviderRuntimeStatus:
    return AIProviderRuntimeStatus(
        provider_id=row["provider_id"],
        source=row["source"],
        status=row["status"],
        reload_interval_seconds=float(row["reload_interval_seconds"]),
        last_reloaded_at=datetime.fromisoformat(row["last_reloaded_at"]),
        active_channels=tuple(
            AIProviderRuntimeChannel(
                label=str(item.get("label", "")),
                weight=max(1, int(item.get("weight", 1))),
                max_parallel_requests=max(
                    1,
                    int(item.get("max_parallel_requests", 1)),
                ),
            )
            for item in json.loads(row["active_channels_json"])
        ),
        error=row["error"],
    )
