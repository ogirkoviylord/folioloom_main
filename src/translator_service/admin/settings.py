from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path


class SettingApplyMode(StrEnum):
    LIVE = "live"
    RESTART_REQUIRED = "restart_required"
    BOOTSTRAP_ONLY = "bootstrap_only"


class SettingValueType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"


@dataclass(frozen=True)
class AdminSettingDefinition:
    key: str
    label: str
    value_type: SettingValueType
    apply_mode: SettingApplyMode
    default_value: str
    minimum: int | float | None = None
    maximum: int | float | None = None
    sensitive: bool = False
    allow_empty: bool = False


@dataclass(frozen=True)
class AdminSettingValue:
    key: str
    label: str
    value: str
    value_type: SettingValueType
    apply_mode: SettingApplyMode
    changed_by: str | None
    changed_at: datetime | None
    sensitive: bool


class SQLiteAdminSettingsStore:
    def __init__(self, db_path: str | Path) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._create_schema()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SQLiteAdminSettingsStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def get_value(self, definition: AdminSettingDefinition) -> AdminSettingValue:
        value = self.get_optional_value(definition)
        if value is not None:
            return value
        return AdminSettingValue(
            key=definition.key,
            label=definition.label,
            value=definition.default_value,
            value_type=definition.value_type,
            apply_mode=definition.apply_mode,
            changed_by=None,
            changed_at=None,
            sensitive=definition.sensitive,
        )

    def get_optional_value(
        self,
        definition: AdminSettingDefinition,
    ) -> AdminSettingValue | None:
        row = self._connection.execute(
            "SELECT * FROM admin_settings WHERE key = ?",
            (definition.key,),
        ).fetchone()
        if row is None:
            return None
        return AdminSettingValue(
            key=definition.key,
            label=definition.label,
            value=row["value"],
            value_type=definition.value_type,
            apply_mode=definition.apply_mode,
            changed_by=row["changed_by"],
            changed_at=datetime.fromisoformat(row["changed_at"]),
            sensitive=definition.sensitive,
        )

    def set_value(
        self,
        definition: AdminSettingDefinition,
        value: str,
        *,
        changed_by: str,
    ) -> AdminSettingValue:
        _validate_value(definition, value)
        now = datetime.now(UTC)
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO admin_settings (key, value, changed_by, changed_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    changed_by = excluded.changed_by,
                    changed_at = excluded.changed_at
                """,
                (definition.key, value, changed_by, now.isoformat()),
            )
        return self.get_value(definition)

    def set_values(
        self,
        values: Sequence[tuple[AdminSettingDefinition, str]],
        *,
        changed_by: str,
    ) -> tuple[AdminSettingValue, ...]:
        for definition, value in values:
            _validate_value(definition, value)
        now = datetime.now(UTC)
        with self._connection:
            self._connection.executemany(
                """
                INSERT INTO admin_settings (key, value, changed_by, changed_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    changed_by = excluded.changed_by,
                    changed_at = excluded.changed_at
                """,
                [
                    (definition.key, value, changed_by, now.isoformat())
                    for definition, value in values
                ],
            )
        return tuple(self.get_value(definition) for definition, _value in values)

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    changed_by TEXT NOT NULL,
                    changed_at TEXT NOT NULL
                )
                """
            )


def _validate_value(definition: AdminSettingDefinition, value: str) -> None:
    if definition.value_type is SettingValueType.INTEGER:
        parsed = int(value)
    elif definition.value_type is SettingValueType.FLOAT:
        parsed = float(value)
    elif definition.value_type is SettingValueType.BOOLEAN:
        if value not in {"true", "false"}:
            raise ValueError(f"Invalid boolean for {definition.key}: {value}")
        return
    else:
        if not value and not definition.allow_empty:
            raise ValueError(f"Setting cannot be empty: {definition.key}")
        return

    if definition.minimum is not None and parsed < definition.minimum:
        raise ValueError(f"Setting below minimum: {definition.key}")
    if definition.maximum is not None and parsed > definition.maximum:
        raise ValueError(f"Setting above maximum: {definition.key}")
