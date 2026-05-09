from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

_STATUS_SEVERITY = {
    "failed": 0,
    "failure": 0,
    "error": 0,
    "cooldown": 1,
}

_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(?:api[_-]?key|token|secret|secret_id|value)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9._-]+"),
    re.compile(r"\b[A-Za-z0-9._-]*api_keys[A-Za-z0-9._-]*\b"),
)


class SQLiteAIProviderValidationStore:
    def __init__(self, db_path: str | Path) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._create_schema()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SQLiteAIProviderValidationStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def record_result(
        self,
        *,
        provider_id: str,
        key_id: str,
        status: str,
        error: str | None,
        actor_id: str,
    ) -> None:
        now = datetime.now(UTC)
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO admin_ai_provider_validations (
                    id, provider_id, key_id, status, error, actor_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    provider_id,
                    key_id,
                    status,
                    _redact_sensitive_text(error),
                    actor_id,
                    now.isoformat(),
                ),
            )

    def latest_by_provider(self) -> Mapping[str, dict[str, str]]:
        rows = self._connection.execute(
            """
            SELECT provider_id, key_id, status, error, created_at
            FROM admin_ai_provider_validations
            ORDER BY datetime(created_at) DESC, rowid DESC
            """
        ).fetchall()
        latest_by_key: dict[tuple[str, str], sqlite3.Row] = {}
        for row in rows:
            key = (row["provider_id"], row["key_id"])
            if key not in latest_by_key:
                latest_by_key[key] = row

        provider_rows: dict[str, list[sqlite3.Row]] = {}
        for row in latest_by_key.values():
            provider_rows.setdefault(row["provider_id"], []).append(row)

        latest: dict[str, dict[str, str]] = {}
        for provider_id, rows_for_provider in provider_rows.items():
            newest = rows_for_provider[0]
            worst = min(
                rows_for_provider,
                key=lambda row: _status_severity(row["status"]),
            )
            metadata = {
                "last_validation_status": worst["status"],
                "last_validated_at": newest["created_at"],
            }
            if worst["error"] is not None:
                metadata["last_error"] = worst["error"]
            latest[provider_id] = metadata
        return latest

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_ai_provider_validations (
                    id TEXT PRIMARY KEY,
                    provider_id TEXT NOT NULL,
                    key_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    actor_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )


def _redact_sensitive_text(value: str | None) -> str | None:
    if value is None:
        return None
    redacted = " ".join(value.split())
    for pattern in _SENSITIVE_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return redacted


def _status_severity(status: str) -> int:
    return _STATUS_SEVERITY.get(status, 2)
