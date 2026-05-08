from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from translator_service.admin.secrets import SecretMetadata, SecretStore


@dataclass(frozen=True)
class AIProviderKeySummary:
    provider_id: str
    key_id: str
    secret_id: str
    label: str
    enabled: bool
    weight: int
    max_parallel_requests: int
    masked_value: str | None
    fingerprint: str | None
    version: int | None
    disabled: bool
    created_at: datetime
    updated_at: datetime


class SQLiteAIProviderKeyStore:
    def __init__(self, db_path: str | Path) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._create_schema()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SQLiteAIProviderKeyStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def add_key(
        self,
        *,
        provider_id: str,
        label: str,
        plaintext: str,
        actor_id: str,
        secret_store: SecretStore,
        weight: int = 1,
        max_parallel_requests: int = 1,
    ) -> AIProviderKeySummary:
        key_id = uuid4().hex
        secret_id = f"{provider_id}.api_keys.{key_id}"
        now = datetime.now(UTC)
        secret = secret_store.put_secret(
            secret_id=secret_id,
            label=label,
            kind="api_key",
            plaintext=plaintext,
            actor_id=actor_id,
        )
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO admin_ai_provider_keys (
                    provider_id, key_id, secret_id, label, enabled, weight,
                    max_parallel_requests, created_at, updated_at, updated_by
                )
                VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    provider_id,
                    key_id,
                    secret_id,
                    label,
                    max(1, int(weight)),
                    max(1, int(max_parallel_requests)),
                    now.isoformat(),
                    now.isoformat(),
                    actor_id,
                ),
            )
        return _summary_from_row(self._key_row(provider_id, key_id), secret)

    def remove_key(
        self,
        *,
        provider_id: str,
        key_id: str,
        actor_id: str,
        secret_store: SecretStore,
    ) -> AIProviderKeySummary:
        row = self._key_row(provider_id, key_id)
        secret = secret_store.disable_secret(row["secret_id"], actor_id=actor_id)
        now = datetime.now(UTC)
        with self._connection:
            self._connection.execute(
                """
                UPDATE admin_ai_provider_keys
                SET enabled = 0, updated_at = ?, updated_by = ?
                WHERE provider_id = ? AND key_id = ?
                """,
                (now.isoformat(), actor_id, provider_id, key_id),
            )
        return _summary_from_row(self._key_row(provider_id, key_id), secret)

    def list_keys(
        self,
        provider_id: str,
        *,
        secret_describer,
        include_removed: bool = False,
    ) -> tuple[AIProviderKeySummary, ...]:
        where = "provider_id = ?"
        parameters: tuple[object, ...] = (provider_id,)
        if not include_removed:
            where += " AND enabled = 1"
        rows = self._connection.execute(
            f"""
            SELECT * FROM admin_ai_provider_keys
            WHERE {where}
            ORDER BY rowid
            """,
            parameters,
        ).fetchall()
        return tuple(
            _summary_from_row(row, secret_describer(row["secret_id"])) for row in rows
        )

    def _key_row(self, provider_id: str, key_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            """
            SELECT * FROM admin_ai_provider_keys
            WHERE provider_id = ? AND key_id = ?
            """,
            (provider_id, key_id),
        ).fetchone()
        if row is None:
            raise KeyError(key_id)
        return row

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_ai_provider_keys (
                    provider_id TEXT NOT NULL,
                    key_id TEXT NOT NULL,
                    secret_id TEXT NOT NULL UNIQUE,
                    label TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    weight INTEGER NOT NULL DEFAULT 1,
                    max_parallel_requests INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    updated_by TEXT NOT NULL,
                    PRIMARY KEY (provider_id, key_id)
                )
                """
            )


def _summary_from_row(
    row: sqlite3.Row,
    secret: SecretMetadata,
) -> AIProviderKeySummary:
    return AIProviderKeySummary(
        provider_id=row["provider_id"],
        key_id=row["key_id"],
        secret_id=row["secret_id"],
        label=row["label"],
        enabled=bool(row["enabled"]),
        weight=int(row["weight"]),
        max_parallel_requests=int(row["max_parallel_requests"]),
        masked_value=secret.masked_value,
        fingerprint=secret.fingerprint,
        version=secret.version,
        disabled=secret.disabled,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
