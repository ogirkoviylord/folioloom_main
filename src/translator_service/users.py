from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import sqlite3


@dataclass(frozen=True)
class User:
    telegram_id: int
    username: str | None
    language_code: str | None
    created_at: datetime
    updated_at: datetime


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._users: dict[int, User] = {}

    def get_by_telegram_id(self, telegram_id: int) -> User | None:
        return self._users.get(telegram_id)

    def save(self, user: User) -> User:
        self._users[user.telegram_id] = user
        return user

    def count(self) -> int:
        return len(self._users)


@dataclass(frozen=True)
class UserSettings:
    telegram_id: int
    interface_language: str | None
    progress_preview_enabled: bool
    created_at: datetime
    updated_at: datetime


class SQLiteUserSettingsRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._closed = False
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self._connection = sqlite3.connect(str(db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._create_schema()

    def close(self) -> None:
        if self._closed:
            return
        self._connection.close()
        self._closed = True

    def get(self, telegram_id: int) -> UserSettings:
        row = self._connection.execute(
            "SELECT * FROM user_settings WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        if row is not None:
            return _settings_from_row(row)

        now = datetime.now(UTC)
        return UserSettings(
            telegram_id=telegram_id,
            interface_language=None,
            progress_preview_enabled=True,
            created_at=now,
            updated_at=now,
        )

    def has_interface_language(self, telegram_id: int) -> bool:
        return self.get(telegram_id).interface_language is not None

    def set_interface_language(self, *, telegram_id: int, language_code: str) -> None:
        current = self.get(telegram_id)
        self._upsert(
            telegram_id=telegram_id,
            interface_language=language_code,
            progress_preview_enabled=current.progress_preview_enabled,
            created_at=current.created_at,
        )

    def set_progress_preview_enabled(self, *, telegram_id: int, enabled: bool) -> None:
        current = self.get(telegram_id)
        self._upsert(
            telegram_id=telegram_id,
            interface_language=current.interface_language,
            progress_preview_enabled=enabled,
            created_at=current.created_at,
        )

    def reset(self, telegram_id: int) -> None:
        with self._connection:
            self._connection.execute(
                "DELETE FROM user_settings WHERE telegram_id = ?",
                (telegram_id,),
            )

    def _upsert(
        self,
        *,
        telegram_id: int,
        interface_language: str | None,
        progress_preview_enabled: bool,
        created_at: datetime,
    ) -> None:
        now = datetime.now(UTC)
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO user_settings (
                    telegram_id, interface_language, progress_preview_enabled,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    interface_language = excluded.interface_language,
                    progress_preview_enabled = excluded.progress_preview_enabled,
                    updated_at = excluded.updated_at
                """,
                (
                    telegram_id,
                    interface_language,
                    1 if progress_preview_enabled else 0,
                    _to_db_time(created_at),
                    _to_db_time(now),
                ),
            )

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_settings (
                    telegram_id INTEGER PRIMARY KEY,
                    interface_language TEXT,
                    progress_preview_enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )


def register_or_update_user(
    repository: InMemoryUserRepository,
    *,
    telegram_id: int,
    username: str | None,
    language_code: str | None,
) -> User:
    now = datetime.now(UTC)
    existing = repository.get_by_telegram_id(telegram_id)

    if existing is None:
        return repository.save(
            User(
                telegram_id=telegram_id,
                username=username,
                language_code=language_code,
                created_at=now,
                updated_at=now,
            )
        )

    return repository.save(
        User(
            telegram_id=existing.telegram_id,
            username=username,
            language_code=language_code,
            created_at=existing.created_at,
            updated_at=now,
        )
    )


def _settings_from_row(row: sqlite3.Row) -> UserSettings:
    return UserSettings(
        telegram_id=int(row["telegram_id"]),
        interface_language=row["interface_language"],
        progress_preview_enabled=bool(row["progress_preview_enabled"]),
        created_at=_from_db_time(row["created_at"]),
        updated_at=_from_db_time(row["updated_at"]),
    )


def _to_db_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _from_db_time(value: str) -> datetime:
    return datetime.fromisoformat(value)
