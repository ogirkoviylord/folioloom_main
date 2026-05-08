from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from translator_service.admin.rbac import AdminRole


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


@dataclass(frozen=True)
class AuditEvent:
    id: str
    actor_id: str
    role: AdminRole
    action: str
    target_type: str
    target_id: str
    outcome: AuditOutcome
    reason: str | None
    metadata_json: str
    created_at: datetime


class SQLiteAdminAuditLog:
    def __init__(self, db_path: str | Path) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._create_schema()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SQLiteAdminAuditLog:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def record(
        self,
        *,
        actor_id: str,
        role: AdminRole,
        action: str,
        target_type: str,
        target_id: str,
        outcome: AuditOutcome,
        reason: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> AuditEvent:
        now = datetime.now(UTC)
        event_id = uuid4().hex
        safe_reason = _redact_text(reason)
        safe_metadata = _redact_metadata(metadata or {})
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO admin_audit_events (
                    id, actor_id, role, action, target_type, target_id,
                    outcome, reason, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    actor_id,
                    role.value,
                    action,
                    target_type,
                    target_id,
                    outcome.value,
                    safe_reason,
                    json.dumps(safe_metadata, sort_keys=True),
                    now.isoformat(),
                ),
            )
        return self.list_events(limit=1)[0]

    def list_events(self, *, limit: int = 50) -> list[AuditEvent]:
        rows = self._connection.execute(
            """
            SELECT * FROM admin_audit_events
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (max(1, limit),),
        ).fetchall()
        return [_event_from_row(row) for row in rows]

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_audit_events (
                    id TEXT PRIMARY KEY,
                    actor_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    reason TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )


def _event_from_row(row: sqlite3.Row) -> AuditEvent:
    return AuditEvent(
        id=row["id"],
        actor_id=row["actor_id"],
        role=AdminRole(row["role"]),
        action=row["action"],
        target_type=row["target_type"],
        target_id=row["target_id"],
        outcome=AuditOutcome(row["outcome"]),
        reason=row["reason"],
        metadata_json=row["metadata_json"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _redact_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"sk-[a-zA-Z0-9_-]+", "[redacted]", value)
    value = re.sub(r"\b\d{6,}:[a-zA-Z0-9_-]+\b", "[redacted]", value)
    return value[:500]


def _redact_metadata(metadata: dict[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in metadata.items():
        if "secret" in key.lower() or "token" in key.lower() or "key" in key.lower():
            safe[key] = "[redacted]"
        elif isinstance(value, str):
            safe[key] = _redact_text(value)
        elif isinstance(value, int | float | bool) or value is None:
            safe[key] = value
        else:
            safe[key] = str(value)[:200]
    return safe
