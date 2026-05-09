from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4


class ActivityActorType(StrEnum):
    USER = "user"
    ADMIN = "admin"
    SYSTEM = "system"
    WORKER = "worker"


class ActivitySurface(StrEnum):
    BOT = "bot"
    ADMIN = "admin"
    WORKER = "worker"
    SECURITY = "security"


class ActivityOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    BLOCKED = "blocked"
    IGNORED = "ignored"


@dataclass(frozen=True)
class UserActivityEventInput:
    actor_type: ActivityActorType | str
    actor_id: str | None
    surface: ActivitySurface | str
    event_type: str
    action: str
    outcome: ActivityOutcome | str = ActivityOutcome.SUCCESS
    channel: str | None = None
    channel_user_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    job_id: str | None = None
    order_id: str | None = None
    translation_run_dir: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class UserActivityEvent:
    id: str
    created_at: datetime
    actor_type: str
    actor_id: str | None
    channel: str | None
    channel_user_id: str | None
    surface: str
    event_type: str
    action: str
    target_type: str | None
    target_id: str | None
    outcome: str
    job_id: str | None
    order_id: str | None
    translation_run_dir: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class UserProfile:
    user_id: str
    channel: str
    channel_user_id: str
    interface_language: str | None
    progress_preview_enabled: bool | None
    default_source_language: str | None
    last_target_language: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    security_state: str
    metadata: dict[str, Any]


class SQLiteUserActivityStore:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._lock = RLock()
        self._connection = sqlite3.connect(self._db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._ensure_schema()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> SQLiteUserActivityStore:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def record_event(self, event: UserActivityEventInput) -> UserActivityEvent:
        event_id = uuid4().hex
        created_at = _now()
        actor_type = _enum_value(event.actor_type)
        surface = _enum_value(event.surface)
        outcome = _enum_value(event.outcome)
        metadata = _sanitize_metadata(event.metadata or {})
        metadata_json = _json_dumps(metadata)

        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO user_activity_events (
                    id, created_at, actor_type, actor_id, channel,
                    channel_user_id, surface, event_type, action,
                    target_type, target_id, outcome, job_id, order_id,
                    translation_run_dir, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    _format_datetime(created_at),
                    actor_type,
                    event.actor_id,
                    event.channel,
                    event.channel_user_id,
                    surface,
                    event.event_type,
                    event.action,
                    event.target_type,
                    event.target_id,
                    outcome,
                    event.job_id,
                    event.order_id,
                    event.translation_run_dir,
                    metadata_json,
                ),
            )
            self._upsert_profile_for_event(
                actor_type=actor_type,
                actor_id=event.actor_id,
                channel=event.channel,
                channel_user_id=event.channel_user_id,
                event_type=event.event_type,
                surface=surface,
                outcome=outcome,
                metadata=metadata,
                seen_at=created_at,
            )

        return UserActivityEvent(
            id=event_id,
            created_at=created_at,
            actor_type=actor_type,
            actor_id=event.actor_id,
            channel=event.channel,
            channel_user_id=event.channel_user_id,
            surface=surface,
            event_type=event.event_type,
            action=event.action,
            target_type=event.target_type,
            target_id=event.target_id,
            outcome=outcome,
            job_id=event.job_id,
            order_id=event.order_id,
            translation_run_dir=event.translation_run_dir,
            metadata=metadata,
        )

    def list_events(
        self,
        *,
        actor_id: str | None = None,
        channel_user_id: str | None = None,
        surface: ActivitySurface | str | None = None,
        event_type: str | None = None,
        action: str | None = None,
        outcome: ActivityOutcome | str | None = None,
        job_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> tuple[UserActivityEvent, ...]:
        where = []
        params: list[Any] = []
        _add_filter(where, params, "actor_id", actor_id)
        _add_filter(where, params, "channel_user_id", channel_user_id)
        _add_filter(where, params, "surface", _enum_value(surface) if surface else None)
        _add_filter(where, params, "event_type", event_type)
        _add_filter(where, params, "action", action)
        _add_filter(where, params, "outcome", _enum_value(outcome) if outcome else None)
        _add_filter(where, params, "job_id", job_id)
        if date_from:
            where.append("created_at >= ?")
            params.append(date_from)
        if date_to:
            where.append("created_at <= ?")
            params.append(_inclusive_date_to(date_to))
        predicate = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(max(1, min(limit, 500)))
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT * FROM user_activity_events
                {predicate}
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return tuple(_event_from_row(row) for row in rows)

    def get_user_profile(self, user_id: str) -> UserProfile | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM user_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return _profile_from_row(row)

    def list_user_profiles(
        self,
        *,
        security_state: str | None = None,
        limit: int = 100,
    ) -> tuple[UserProfile, ...]:
        params: list[Any] = []
        where = ""
        if security_state:
            where = "WHERE security_state = ?"
            params.append(security_state)
        params.append(max(1, min(limit, 500)))
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT * FROM user_profiles
                {where}
                ORDER BY last_seen_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return tuple(_profile_from_row(row) for row in rows)

    def _ensure_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_activity_events (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    actor_type TEXT NOT NULL,
                    actor_id TEXT,
                    channel TEXT,
                    channel_user_id TEXT,
                    surface TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_type TEXT,
                    target_id TEXT,
                    outcome TEXT NOT NULL,
                    job_id TEXT,
                    order_id TEXT,
                    translation_run_dir TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    channel TEXT NOT NULL,
                    channel_user_id TEXT NOT NULL,
                    interface_language TEXT,
                    progress_preview_enabled INTEGER,
                    default_source_language TEXT,
                    last_target_language TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    security_state TEXT NOT NULL DEFAULT 'normal',
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_user_activity_created_at
                ON user_activity_events(created_at)
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_user_activity_actor
                ON user_activity_events(actor_id, created_at)
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_user_activity_surface_outcome
                ON user_activity_events(surface, outcome, created_at)
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_user_activity_job
                ON user_activity_events(job_id)
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_user_profiles_last_seen
                ON user_profiles(last_seen_at)
                """
            )

    def _upsert_profile_for_event(
        self,
        *,
        actor_type: str,
        actor_id: str | None,
        channel: str | None,
        channel_user_id: str | None,
        event_type: str,
        surface: str,
        outcome: str,
        metadata: dict[str, Any],
        seen_at: datetime,
    ) -> None:
        if actor_type != ActivityActorType.USER.value or not actor_id:
            return
        if not channel or not channel_user_id:
            return

        existing = self._connection.execute(
            "SELECT * FROM user_profiles WHERE user_id = ?",
            (actor_id,),
        ).fetchone()
        interface_language = (
            existing["interface_language"] if existing is not None else None
        )
        progress_preview_enabled = (
            existing["progress_preview_enabled"] if existing is not None else None
        )
        default_source_language = (
            existing["default_source_language"] if existing is not None else None
        )
        last_target_language = (
            existing["last_target_language"] if existing is not None else None
        )
        security_state = (
            existing["security_state"] if existing is not None else "normal"
        )
        if event_type == "user.interface_language.changed":
            interface_language = _metadata_string(
                metadata,
                "language_code",
                "new_value",
                "interface_language",
            )
        if event_type == "user.setting.changed":
            setting_key = _metadata_string(metadata, "setting_key")
            if setting_key == "progress_preview_enabled":
                progress_preview_enabled = 1 if bool(metadata.get("new_value")) else 0
        if event_type == "translation.target_language.selected":
            last_target_language = _metadata_string(metadata, "target_language")
        if (
            surface == ActivitySurface.SECURITY.value
            and outcome == ActivityOutcome.BLOCKED.value
        ):
            security_state = metadata.get("security_state") or "watched"

        first_seen_at = (
            _parse_datetime(existing["first_seen_at"])
            if existing is not None
            else seen_at
        )
        self._connection.execute(
            """
            INSERT INTO user_profiles (
                user_id, channel, channel_user_id, interface_language,
                progress_preview_enabled, default_source_language,
                last_target_language, first_seen_at, last_seen_at,
                security_state, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                channel = excluded.channel,
                channel_user_id = excluded.channel_user_id,
                interface_language = excluded.interface_language,
                progress_preview_enabled = excluded.progress_preview_enabled,
                default_source_language = excluded.default_source_language,
                last_target_language = excluded.last_target_language,
                last_seen_at = excluded.last_seen_at,
                security_state = excluded.security_state
            """,
            (
                actor_id,
                channel,
                channel_user_id,
                interface_language,
                progress_preview_enabled,
                default_source_language,
                last_target_language,
                _format_datetime(first_seen_at),
                _format_datetime(seen_at),
                security_state,
                "{}",
            ),
        )


def _event_from_row(row: sqlite3.Row) -> UserActivityEvent:
    return UserActivityEvent(
        id=row["id"],
        created_at=_parse_datetime(row["created_at"]),
        actor_type=row["actor_type"],
        actor_id=row["actor_id"],
        channel=row["channel"],
        channel_user_id=row["channel_user_id"],
        surface=row["surface"],
        event_type=row["event_type"],
        action=row["action"],
        target_type=row["target_type"],
        target_id=row["target_id"],
        outcome=row["outcome"],
        job_id=row["job_id"],
        order_id=row["order_id"],
        translation_run_dir=row["translation_run_dir"],
        metadata=_json_loads(row["metadata_json"]),
    )


def _profile_from_row(row: sqlite3.Row) -> UserProfile:
    progress_preview_enabled = row["progress_preview_enabled"]
    return UserProfile(
        user_id=row["user_id"],
        channel=row["channel"],
        channel_user_id=row["channel_user_id"],
        interface_language=row["interface_language"],
        progress_preview_enabled=(
            bool(progress_preview_enabled)
            if progress_preview_enabled is not None
            else None
        ),
        default_source_language=row["default_source_language"],
        last_target_language=row["last_target_language"],
        first_seen_at=_parse_datetime(row["first_seen_at"]),
        last_seen_at=_parse_datetime(row["last_seen_at"]),
        security_state=row["security_state"],
        metadata=_json_loads(row["metadata_json"]),
    )


def _add_filter(
    where: list[str],
    params: list[Any],
    column: str,
    value: str | None,
) -> None:
    if not value:
        return
    where.append(f"{column} = ?")
    params.append(value)


def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): _sanitize_value(str(key), value) for key, value in metadata.items()
    }


def _sanitize_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if any(token in lowered for token in ("secret", "token", "password", "key")):
        return "[redacted]"
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _truncate(value)
    if isinstance(value, list | tuple):
        return [_sanitize_value(key, item) for item in value[:20]]
    if isinstance(value, dict):
        return {
            str(child_key): _sanitize_value(str(child_key), child_value)
            for child_key, child_value in list(value.items())[:50]
        }
    return _truncate(str(value))


def _truncate(value: str, max_length: int = 600) -> str:
    if len(value) <= max_length:
        return value
    return value[:max_length] + "..."


def _json_dumps(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: str) -> dict[str, Any]:
    try:
        loaded = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _enum_value(value: StrEnum | str) -> str:
    return value.value if isinstance(value, StrEnum) else str(value)


def _metadata_string(metadata: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _now() -> datetime:
    return datetime.now(UTC)


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _inclusive_date_to(value: str) -> str:
    if len(value) == 10:
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return value
        return f"{value}T23:59:59.999999+00:00"
    return value


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)
