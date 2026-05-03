from dataclasses import dataclass
from datetime import UTC, datetime


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

