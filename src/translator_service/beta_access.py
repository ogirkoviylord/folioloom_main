from __future__ import annotations

import re
from dataclasses import dataclass

from translator_service.admin.settings import (
    AdminSettingDefinition,
    SettingApplyMode,
    SettingValueType,
    SQLiteAdminSettingsStore,
)
from translator_service.config import Settings


BETA_ALLOWLIST_SETTING = AdminSettingDefinition(
    key="beta.allowlist_telegram_ids",
    label="Beta allowlist Telegram IDs",
    value_type=SettingValueType.STRING,
    apply_mode=SettingApplyMode.LIVE,
    default_value="",
    allow_empty=True,
)

BETA_ALLOWLIST_ENABLED_SETTING = AdminSettingDefinition(
    key="beta.allowlist_enabled",
    label="Beta allowlist enabled",
    value_type=SettingValueType.BOOLEAN,
    apply_mode=SettingApplyMode.LIVE,
    default_value="false",
)


class BetaAccessDenied(PermissionError):
    pass


@dataclass(frozen=True)
class BetaAccessPolicy:
    allowed_telegram_ids: frozenset[int]
    enforcement_enabled: bool = False

    @classmethod
    def from_telegram_ids(
        cls,
        ids: tuple[int, ...] | list[int] | set[int],
        *,
        enabled: bool = True,
    ):
        return cls(
            allowed_telegram_ids=frozenset(
                int(user_id) for user_id in ids if int(user_id) > 0
            ),
            enforcement_enabled=enabled,
        )

    @property
    def enabled(self) -> bool:
        return self.enforcement_enabled

    def is_allowed(self, user_telegram_id: int) -> bool:
        if not self.enforcement_enabled:
            return True
        return int(user_telegram_id) in self.allowed_telegram_ids

    def assert_allowed(self, user_telegram_id: int) -> None:
        if self.is_allowed(user_telegram_id):
            return
        raise BetaAccessDenied(
            "FolioLoom is invite-only during the closed beta. "
            "Ask the owner to add your Telegram ID to the beta allowlist."
        )


class SQLiteBackedBetaAccessPolicy:
    def __init__(
        self,
        *,
        admin_db_path: str,
        fallback_telegram_ids: tuple[int, ...],
        fallback_enabled: bool = False,
    ):
        self._admin_db_path = admin_db_path
        self._fallback_telegram_ids = fallback_telegram_ids
        self._fallback_enabled = fallback_enabled

    @property
    def allowed_telegram_ids(self) -> frozenset[int]:
        return self._current_policy().allowed_telegram_ids

    @property
    def enforcement_enabled(self) -> bool:
        return self._current_policy().enforcement_enabled

    def is_allowed(self, user_telegram_id: int) -> bool:
        return self._current_policy().is_allowed(user_telegram_id)

    def assert_allowed(self, user_telegram_id: int) -> None:
        self._current_policy().assert_allowed(user_telegram_id)

    def _current_policy(self) -> BetaAccessPolicy:
        ids = self._fallback_telegram_ids
        enabled = self._fallback_enabled
        try:
            with SQLiteAdminSettingsStore(self._admin_db_path) as store:
                saved = store.get_optional_value(BETA_ALLOWLIST_SETTING)
                saved_enabled = store.get_optional_value(BETA_ALLOWLIST_ENABLED_SETTING)
        except Exception:
            saved = None
            saved_enabled = None
        if saved is not None:
            ids = parse_telegram_id_list(saved.value)
        if saved_enabled is not None:
            enabled = saved_enabled.value == "true"
        return BetaAccessPolicy.from_telegram_ids(ids, enabled=enabled)


def parse_telegram_id_list(raw: str) -> tuple[int, ...]:
    ids: list[int] = []
    seen: set[int] = set()
    for part in re.split(r"[\s,;]+", raw):
        if not part:
            continue
        try:
            user_id = int(part)
        except ValueError:
            continue
        if user_id <= 0 or user_id in seen:
            continue
        seen.add(user_id)
        ids.append(user_id)
    return tuple(ids)


def format_telegram_id_list(ids: tuple[int, ...] | list[int] | set[int]) -> str:
    return "\n".join(str(user_id) for user_id in sorted(set(ids)))


def load_beta_access_policy(settings: Settings) -> BetaAccessPolicy:
    return SQLiteBackedBetaAccessPolicy(
        admin_db_path=settings.admin_db_path,
        fallback_telegram_ids=settings.beta_allowlist_telegram_ids,
        fallback_enabled=settings.beta_allowlist_enabled,
    )._current_policy()
