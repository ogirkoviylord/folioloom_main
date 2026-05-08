from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from translator_service.admin.integrations import (
    IntegrationDefinition,
    IntegrationSecretSummary,
)
from translator_service.admin.secrets import (
    SecretMetadata,
    SecretNotFound,
    SecretStore,
)


@dataclass(frozen=True)
class IntegrationConnectionSummary:
    integration_id: str
    connection_id: str
    label: str
    enabled: bool
    secret_values: tuple[IntegrationSecretSummary, ...]
    created_at: datetime
    updated_at: datetime


class SQLiteIntegrationConnectionStore:
    def __init__(self, db_path: str | Path) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._create_schema()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SQLiteIntegrationConnectionStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def add_connection(
        self,
        *,
        definition: IntegrationDefinition,
        label: str,
        secret_values: dict[str, str],
        actor_id: str,
        secret_store: SecretStore,
    ) -> IntegrationConnectionSummary:
        label = label.strip() or "unnamed"
        _validate_required_secret_values(definition, secret_values)
        connection_id = uuid4().hex
        now = datetime.now(UTC)
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO admin_integration_connections (
                    integration_id, connection_id, label, enabled,
                    created_at, updated_at, updated_by
                )
                VALUES (?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    definition.integration_id,
                    connection_id,
                    label,
                    now.isoformat(),
                    now.isoformat(),
                    actor_id,
                ),
            )
        for requirement in definition.secret_requirements:
            plaintext = secret_values.get(requirement.secret_id, "")
            if not plaintext:
                continue
            secret_store.put_secret(
                secret_id=_connection_secret_id(
                    definition.integration_id,
                    connection_id,
                    requirement.secret_id,
                ),
                label=f"{label} {requirement.label}",
                kind=requirement.kind,
                plaintext=plaintext,
                actor_id=actor_id,
            )
        return self._summary(
            definition,
            self._connection_row(definition.integration_id, connection_id),
            secret_describer=secret_store.describe_secret,
        )

    def remove_connection(
        self,
        *,
        definition: IntegrationDefinition,
        connection_id: str,
        actor_id: str,
        secret_store: SecretStore,
    ) -> IntegrationConnectionSummary:
        row = self._connection_row(definition.integration_id, connection_id)
        for requirement in definition.secret_requirements:
            try:
                secret_store.disable_secret(
                    _connection_secret_id(
                        definition.integration_id,
                        connection_id,
                        requirement.secret_id,
                    ),
                    actor_id=actor_id,
                )
            except SecretNotFound:
                pass
        now = datetime.now(UTC)
        with self._connection:
            self._connection.execute(
                """
                UPDATE admin_integration_connections
                SET enabled = 0, updated_at = ?, updated_by = ?
                WHERE integration_id = ? AND connection_id = ?
                """,
                (
                    now.isoformat(),
                    actor_id,
                    row["integration_id"],
                    row["connection_id"],
                ),
            )
        return self._summary(
            definition,
            self._connection_row(definition.integration_id, connection_id),
            secret_describer=secret_store.describe_secret,
        )

    def list_connections(
        self,
        definition: IntegrationDefinition,
        *,
        secret_describer,
        include_removed: bool = False,
    ) -> tuple[IntegrationConnectionSummary, ...]:
        where = "integration_id = ?"
        parameters: tuple[object, ...] = (definition.integration_id,)
        if not include_removed:
            where += " AND enabled = 1"
        rows = self._connection.execute(
            f"""
            SELECT * FROM admin_integration_connections
            WHERE {where}
            ORDER BY rowid
            """,
            parameters,
        ).fetchall()
        return tuple(
            self._summary(definition, row, secret_describer=secret_describer)
            for row in rows
        )

    def _connection_row(
        self,
        integration_id: str,
        connection_id: str,
    ) -> sqlite3.Row:
        row = self._connection.execute(
            """
            SELECT * FROM admin_integration_connections
            WHERE integration_id = ? AND connection_id = ?
            """,
            (integration_id, connection_id),
        ).fetchone()
        if row is None:
            raise KeyError(connection_id)
        return row

    def _summary(
        self,
        definition: IntegrationDefinition,
        row: sqlite3.Row,
        *,
        secret_describer,
    ) -> IntegrationConnectionSummary:
        secret_values = tuple(
            _connection_secret_summary(
                definition.integration_id,
                row["connection_id"],
                requirement.secret_id,
                requirement.label,
                requirement.kind,
                requirement.required,
                secret_describer=secret_describer,
            )
            for requirement in definition.secret_requirements
        )
        return IntegrationConnectionSummary(
            integration_id=row["integration_id"],
            connection_id=row["connection_id"],
            label=row["label"],
            enabled=bool(row["enabled"]),
            secret_values=secret_values,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_integration_connections (
                    integration_id TEXT NOT NULL,
                    connection_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    updated_by TEXT NOT NULL,
                    PRIMARY KEY (integration_id, connection_id)
                )
                """
            )


def _connection_secret_summary(
    integration_id: str,
    connection_id: str,
    requirement_secret_id: str,
    label: str,
    kind: str,
    required: bool,
    *,
    secret_describer,
) -> IntegrationSecretSummary:
    secret_id = _connection_secret_id(
        integration_id,
        connection_id,
        requirement_secret_id,
    )
    try:
        metadata: SecretMetadata = secret_describer(secret_id)
    except (KeyError, SecretNotFound):
        return IntegrationSecretSummary(
            secret_id=secret_id,
            label=label,
            kind=kind,
            required=required,
            configured=False,
        )
    return IntegrationSecretSummary(
        secret_id=secret_id,
        label=label,
        kind=kind,
        required=required,
        configured=not metadata.disabled,
        disabled=metadata.disabled,
        masked_value=metadata.masked_value,
        fingerprint=metadata.fingerprint,
        version=metadata.version,
    )


def _validate_required_secret_values(
    definition: IntegrationDefinition,
    secret_values: dict[str, str],
) -> None:
    missing = [
        requirement.label
        for requirement in definition.secret_requirements
        if requirement.required and not secret_values.get(requirement.secret_id, "")
    ]
    if missing:
        raise ValueError(f"Missing required secrets: {', '.join(missing)}")


def _connection_secret_id(
    integration_id: str,
    connection_id: str,
    requirement_secret_id: str,
) -> str:
    return f"{integration_id}.connections.{connection_id}.{requirement_secret_id}"
