from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from translator_service.admin.ai_provider_keys import AIProviderKeySummary
from translator_service.admin.integration_connections import (
    IntegrationConnectionSummary,
)
from translator_service.admin.integrations import (
    IntegrationSecretSummary,
    IntegrationState,
    IntegrationSummary,
)

_DEEPSEEK_PROVIDER_ID = "deepseek"
_DEEPSEEK_ENV_SECRET_ID = "env.deepseek.api_keys"
_TELEGRAM_INTEGRATION_ID = "telegram"
_TELEGRAM_SECRET_ID = "telegram.bot_token"


@dataclass(frozen=True)
class AdminBootstrapConfig:
    deepseek_key_count: int = 0
    telegram_configured: bool = False

    @property
    def has_deepseek_keys(self) -> bool:
        return self.deepseek_key_count > 0


def env_bootstrap_config(
    environ: Mapping[str, str] | None = None,
) -> AdminBootstrapConfig:
    values = environ if environ is not None else os.environ
    deepseek_keys = _deepseek_keys_from_env(values)
    telegram_token = values.get("TELEGRAM_BOT_TOKEN", "")
    return AdminBootstrapConfig(
        deepseek_key_count=len(deepseek_keys),
        telegram_configured=bool(telegram_token.strip()),
    )


def apply_integration_bootstrap(
    summaries: Sequence[IntegrationSummary],
    bootstrap_config: AdminBootstrapConfig,
) -> tuple[IntegrationSummary, ...]:
    return tuple(
        _integration_summary_with_bootstrap(summary, bootstrap_config)
        for summary in summaries
    )


def apply_ai_provider_key_bootstrap(
    key_pools: Mapping[str, Sequence[AIProviderKeySummary]],
    bootstrap_config: AdminBootstrapConfig,
) -> dict[str, tuple[AIProviderKeySummary, ...]]:
    pools = {provider_id: tuple(keys) for provider_id, keys in key_pools.items()}
    if not bootstrap_config.has_deepseek_keys:
        return pools
    deepseek_keys = pools.get(_DEEPSEEK_PROVIDER_ID, ())
    if any(is_env_deepseek_key(key) for key in deepseek_keys):
        return pools
    pools[_DEEPSEEK_PROVIDER_ID] = (
        *deepseek_keys,
        env_deepseek_key_summary(bootstrap_config.deepseek_key_count),
    )
    return pools


def apply_integration_connection_bootstrap(
    connection_groups: Mapping[str, Sequence[IntegrationConnectionSummary]],
    bootstrap_config: AdminBootstrapConfig,
) -> dict[str, tuple[IntegrationConnectionSummary, ...]]:
    groups = {
        integration_id: tuple(connections)
        for integration_id, connections in connection_groups.items()
    }
    if not bootstrap_config.telegram_configured:
        return groups
    telegram_connections = groups.get(_TELEGRAM_INTEGRATION_ID, ())
    if any(
        connection.connection_id == "env-fallback"
        for connection in telegram_connections
    ):
        return groups
    groups[_TELEGRAM_INTEGRATION_ID] = (
        env_telegram_connection_summary(),
        *telegram_connections,
    )
    return groups


def env_deepseek_key_summary(key_count: int) -> AIProviderKeySummary:
    now = datetime.now(UTC)
    return AIProviderKeySummary(
        provider_id=_DEEPSEEK_PROVIDER_ID,
        key_id="env-fallback",
        secret_id=_DEEPSEEK_ENV_SECRET_ID,
        label="server .env",
        enabled=True,
        weight=max(1, key_count),
        max_parallel_requests=1,
        masked_value=f"server .env ({key_count} {_pluralize_key(key_count)})",
        fingerprint=None,
        version=None,
        disabled=False,
        created_at=now,
        updated_at=now,
    )


def env_telegram_connection_summary() -> IntegrationConnectionSummary:
    now = datetime.now(UTC)
    return IntegrationConnectionSummary(
        integration_id=_TELEGRAM_INTEGRATION_ID,
        connection_id="env-fallback",
        label="server .env",
        enabled=True,
        secret_values=(
            IntegrationSecretSummary(
                secret_id=_TELEGRAM_SECRET_ID,
                label="Telegram bot token",
                kind="bot_token",
                required=True,
                configured=True,
                disabled=False,
                masked_value="server .env",
            ),
        ),
        created_at=now,
        updated_at=now,
    )


def is_env_deepseek_key(key: AIProviderKeySummary) -> bool:
    return key.secret_id == _DEEPSEEK_ENV_SECRET_ID


def _deepseek_keys_from_env(environ: Mapping[str, str]) -> tuple[str, ...]:
    key_list = environ.get("DEEPSEEK_API_KEYS", "")
    keys = tuple(key.strip() for key in key_list.split(",") if key.strip())
    if keys:
        return keys
    single_key = environ.get("DEEPSEEK_API_KEY", "").strip()
    return (single_key,) if single_key else ()


def _integration_summary_with_bootstrap(
    summary: IntegrationSummary,
    bootstrap_config: AdminBootstrapConfig,
) -> IntegrationSummary:
    if (
        summary.integration_id != _TELEGRAM_INTEGRATION_ID
        or not bootstrap_config.telegram_configured
    ):
        return summary
    secrets = tuple(_telegram_secret_with_bootstrap(secret) for secret in summary.secrets)
    return replace(summary, state=IntegrationState.CONFIGURED, secrets=secrets)


def _telegram_secret_with_bootstrap(
    secret: IntegrationSecretSummary,
) -> IntegrationSecretSummary:
    if secret.secret_id != _TELEGRAM_SECRET_ID or secret.configured:
        return secret
    return replace(
        secret,
        configured=True,
        disabled=False,
        masked_value="server .env",
    )


def _pluralize_key(key_count: int) -> str:
    return "key" if key_count == 1 else "keys"
